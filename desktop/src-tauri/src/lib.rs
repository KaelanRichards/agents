//! Agents desktop — Tauri 2 core.
//!
//! The Rust side is the trust boundary: it holds the agentd token (macOS Keychain via `keyring`),
//! proxies every agentd call (so the token never reaches JS and CORS never applies), runs a
//! background poller that streams snapshots to the UI and fires native notifications when the
//! approval inbox grows, and renders the menubar/tray status pill. The frontend is dependency-free
//! static HTML/JS talking to these `#[tauri::command]`s via the global `window.__TAURI__` API.

use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_notification::NotificationExt;

mod pty;

const KEYRING_SERVICE: &str = "dev.kaelan.agents";

/// A reachable agentd backend (local laptop or remote VM).
#[derive(Clone, Debug, Serialize, Deserialize)]
struct Connection {
    name: String,
    base_url: String,
}

impl Default for Connection {
    fn default() -> Self {
        Connection {
            name: "local".into(),
            base_url: "http://127.0.0.1:8788".into(),
        }
    }
}

#[derive(Default, Serialize, Deserialize)]
struct ConnStore {
    active: String,
    connections: Vec<Connection>,
}

struct AppState {
    store: Mutex<ConnStore>,
    /// last seen pending-approval count, for notification edge-detection
    last_pending: Mutex<i64>,
}

// ---------------------------------------------------------------------------
// Connection persistence: list of {name, base_url} on disk; tokens in Keychain.
// ---------------------------------------------------------------------------

fn store_path(app: &AppHandle) -> std::path::PathBuf {
    let dir = app
        .path()
        .app_config_dir()
        .unwrap_or_else(|_| std::path::PathBuf::from("."));
    let _ = std::fs::create_dir_all(&dir);
    dir.join("connections.json")
}

fn load_store(app: &AppHandle) -> ConnStore {
    let path = store_path(app);
    if let Ok(text) = std::fs::read_to_string(&path) {
        if let Ok(s) = serde_json::from_str::<ConnStore>(&text) {
            if !s.connections.is_empty() {
                return s;
            }
        }
    }
    let local = Connection::default();
    ConnStore {
        active: local.name.clone(),
        connections: vec![local],
    }
}

fn save_store(app: &AppHandle, store: &ConnStore) {
    if let Ok(text) = serde_json::to_string_pretty(store) {
        let _ = std::fs::write(store_path(app), text);
    }
}

fn active_conn(state: &State<AppState>) -> Connection {
    let store = state.store.lock().unwrap();
    store
        .connections
        .iter()
        .find(|c| c.name == store.active)
        .cloned()
        .unwrap_or_default()
}

fn token_for(name: &str) -> Option<String> {
    keyring::Entry::new(KEYRING_SERVICE, name)
        .ok()
        .and_then(|e| e.get_password().ok())
        .filter(|t| !t.is_empty())
}

// ---------------------------------------------------------------------------
// agentd HTTP — blocking reqwest, token attached in Rust.
// ---------------------------------------------------------------------------

fn http_client() -> reqwest::blocking::Client {
    reqwest::blocking::Client::builder()
        .cookie_store(true)
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .expect("client")
}

fn get_json(conn: &Connection, path: &str) -> anyhow::Result<serde_json::Value> {
    let mut req = http_client().get(format!("{}{}", conn.base_url, path));
    if let Some(tok) = token_for(&conn.name) {
        req = req.header("x-agentd-token", tok);
    }
    Ok(req.send()?.error_for_status()?.json()?)
}

/// POST a mutation through /api/action. Fetches a CSRF token first (cookie + value), reusing the
/// client's cookie jar so the same-origin CSRF check passes — exactly the dashweb/agentd contract.
fn post_action(
    conn: &Connection,
    action: &str,
    args: serde_json::Value,
) -> anyhow::Result<serde_json::Value> {
    let client = http_client();
    let tok = token_for(&conn.name);
    let mut csrf_req = client.get(format!("{}/api/csrf", conn.base_url));
    if let Some(t) = &tok {
        csrf_req = csrf_req.header("x-agentd-token", t);
    }
    let csrf: serde_json::Value = csrf_req.send()?.error_for_status()?.json()?;
    let csrf_token = csrf
        .get("csrf")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let body = serde_json::json!({ "action": action, "args": args });
    let mut req = client
        .post(format!("{}/api/action", conn.base_url))
        .header("x-csrf-token", csrf_token)
        .json(&body);
    if let Some(t) = &tok {
        req = req.header("x-agentd-token", t);
    }
    Ok(req.send()?.error_for_status()?.json()?)
}

// ---------------------------------------------------------------------------
// Commands exposed to the frontend
// ---------------------------------------------------------------------------

#[tauri::command]
fn list_connections(state: State<AppState>) -> serde_json::Value {
    let store = state.store.lock().unwrap();
    let conns: Vec<serde_json::Value> = store
        .connections
        .iter()
        .map(|c| {
            serde_json::json!({
                "name": c.name,
                "base_url": c.base_url,
                "active": c.name == store.active,
                "has_token": token_for(&c.name).is_some(),
            })
        })
        .collect();
    serde_json::json!({ "active": store.active, "connections": conns })
}

#[tauri::command]
fn set_active(app: AppHandle, state: State<AppState>, name: String) -> Result<(), String> {
    let mut store = state.store.lock().unwrap();
    if !store.connections.iter().any(|c| c.name == name) {
        return Err(format!("unknown connection: {name}"));
    }
    store.active = name;
    save_store(&app, &store);
    Ok(())
}

#[tauri::command]
fn upsert_connection(
    app: AppHandle,
    state: State<AppState>,
    name: String,
    base_url: String,
    token: Option<String>,
) -> Result<(), String> {
    {
        let mut store = state.store.lock().unwrap();
        match store.connections.iter_mut().find(|c| c.name == name) {
            Some(c) => c.base_url = base_url.clone(),
            None => store.connections.push(Connection {
                name: name.clone(),
                base_url,
            }),
        }
        save_store(&app, &store);
    }
    if let Some(tok) = token {
        let entry = keyring::Entry::new(KEYRING_SERVICE, &name).map_err(|e| e.to_string())?;
        if tok.is_empty() {
            let _ = entry.delete_credential();
        } else {
            entry.set_password(&tok).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

#[tauri::command]
fn agentd_get(state: State<AppState>, path: String) -> Result<serde_json::Value, String> {
    let conn = active_conn(&state);
    get_json(&conn, &path).map_err(|e| e.to_string())
}

#[tauri::command]
fn agentd_action(
    state: State<AppState>,
    action: String,
    args: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let conn = active_conn(&state);
    post_action(&conn, &action, args).map_err(|e| e.to_string())
}

#[tauri::command]
fn health(state: State<AppState>) -> serde_json::Value {
    let conn = active_conn(&state);
    match get_json(&conn, "/healthz") {
        Ok(v) => serde_json::json!({ "ok": true, "conn": conn.name, "detail": v }),
        Err(e) => serde_json::json!({ "ok": false, "conn": conn.name, "error": e.to_string() }),
    }
}

/// Start the local agentd if it isn't already answering. Spawns the `bin/agentd` launcher detached.
#[tauri::command]
fn start_local_agentd() -> Result<String, String> {
    let local = Connection::default();
    if get_json(&local, "/healthz").is_ok() {
        return Ok("already running".into());
    }
    let home = std::env::var("HOME").map_err(|e| e.to_string())?;
    let launcher = format!("{home}/.config/agents/bin/agentd");
    std::process::Command::new("/bin/sh")
        .arg("-lc")
        .arg(format!("nohup {launcher} >/tmp/agentd.log 2>&1 &"))
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok("starting".into())
}

// ---------------------------------------------------------------------------
// Local document editing (Config + Memory) — allowlisted, laptop-only.
//
// Canonical sources live in ~/.config/agents and `mcp-sync`/`agents-sync` own propagation, so the
// app edits the *source* files and offers a Sync action. Writes are restricted to a small
// allowlist and every path is canonicalized and re-checked to be inside AGENTS_HOME, so a crafted
// relative path cannot escape (defense-in-depth alongside the canonical-source rule).
// ---------------------------------------------------------------------------

fn agents_home() -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    std::path::PathBuf::from(format!("{home}/.config/agents"))
}

fn editable_path(rel: &str) -> Result<std::path::PathBuf, String> {
    let allowed = rel == "mcp.json"
        || (rel.starts_with("profiles/") && rel.ends_with(".json") && !rel.contains(".."))
        || (rel.starts_with("assistant/memory/") && rel.ends_with(".md") && !rel.contains(".."));
    if !allowed {
        return Err(format!("path not editable: {rel}"));
    }
    let base = agents_home();
    let full = base.join(rel);
    let check = if full.exists() {
        full.canonicalize().map_err(|e| e.to_string())?
    } else {
        let parent = full.parent().ok_or("no parent")?;
        parent
            .canonicalize()
            .map_err(|e| e.to_string())?
            .join(full.file_name().ok_or("no file name")?)
    };
    if !check.starts_with(base.canonicalize().map_err(|e| e.to_string())?) {
        return Err("path escapes agents home".into());
    }
    Ok(full)
}

#[tauri::command]
fn read_doc(rel: String) -> Result<String, String> {
    let path = editable_path(&rel)?;
    std::fs::read_to_string(&path).map_err(|e| e.to_string())
}

#[tauri::command]
fn write_doc(rel: String, content: String) -> Result<(), String> {
    let path = editable_path(&rel)?;
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    std::fs::write(&path, content).map_err(|e| e.to_string())
}

#[tauri::command]
fn list_memory() -> Result<Vec<String>, String> {
    let dir = agents_home().join("assistant/memory");
    let mut out = vec![];
    if let Ok(entries) = std::fs::read_dir(&dir) {
        for e in entries.flatten() {
            if let Some(name) = e.file_name().to_str() {
                if name.ends_with(".md") {
                    out.push(format!("assistant/memory/{name}"));
                }
            }
        }
    }
    out.sort();
    Ok(out)
}

// ---------------------------------------------------------------------------
// PTY attach — interactive agent sessions in an embedded terminal.
//
// pty_spawn resolves the active connection's host (empty for local → agentp runs here; a tailnet
// host for the VM → ssh -t into it) so "Attach" honors the same local/VM switch as everything else.
// ---------------------------------------------------------------------------

fn host_for_active(state: &State<AppState>) -> String {
    let conn = active_conn(state);
    if conn.name == "local" {
        return String::new();
    }
    if let Some(rest) = conn.base_url.strip_prefix("ssh://") {
        return rest.to_string();
    }
    "agents".to_string()
}

#[tauri::command]
fn pty_spawn(
    app: AppHandle,
    state: State<AppState>,
    pty_state: State<pty::PtyState>,
    id: String,
    profile: String,
    engine: String,
    cols: u16,
    rows: u16,
) -> Result<String, String> {
    let host = host_for_active(&state);
    pty::spawn(&app, &pty_state, id, profile, engine, host, cols, rows).map_err(|e| e.to_string())
}

#[tauri::command]
fn pty_write(pty_state: State<pty::PtyState>, id: String, data: String) -> Result<(), String> {
    pty::write_input(&pty_state, &id, &data).map_err(|e| e.to_string())
}

#[tauri::command]
fn pty_resize(
    pty_state: State<pty::PtyState>,
    id: String,
    cols: u16,
    rows: u16,
) -> Result<(), String> {
    pty::resize(&pty_state, &id, cols, rows).map_err(|e| e.to_string())
}

#[tauri::command]
fn pty_kill(pty_state: State<pty::PtyState>, id: String) {
    pty::kill(&pty_state, &id);
}

// ---------------------------------------------------------------------------
// Tray + background poller
// ---------------------------------------------------------------------------

fn update_tray(app: &AppHandle, pending: i64, ledger_ok: bool, reachable: bool) {
    if let Some(tray) = app.tray_by_id("main") {
        let pill = if !reachable {
            "● offline".to_string()
        } else if pending > 0 {
            format!("● {pending}")
        } else if !ledger_ok {
            "● ⚠".to_string()
        } else {
            "●".to_string()
        };
        let _ = tray.set_title(Some(&pill));
        let _ = tray.set_tooltip(Some(&format!(
            "Agents — {} pending approval(s), ledger {}",
            pending,
            if ledger_ok { "ok" } else { "BROKEN" }
        )));
    }
}

fn spawn_poller(app: AppHandle) {
    std::thread::spawn(move || loop {
        let state = app.state::<AppState>();
        let conn = active_conn(&state);
        match get_json(&conn, "/api/snapshot") {
            Ok(snap) => {
                let pending = snap
                    .get("pending_approvals")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0);
                let ledger_ok = snap
                    .get("ledger_ok")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(true);
                update_tray(&app, pending, ledger_ok, true);
                let _ = app.emit("snapshot", &snap);

                // Edge-detect a growing inbox -> native notification.
                let mut last = state.last_pending.lock().unwrap();
                if pending > *last {
                    let delta = pending - *last;
                    let _ = app
                        .notification()
                        .builder()
                        .title("Approval needed")
                        .body(format!(
                            "{delta} new agent action awaiting approval ({pending} pending)."
                        ))
                        .show();
                }
                *last = pending;
            }
            Err(_) => {
                update_tray(&app, 0, true, false);
                let _ = app.emit("offline", &conn.name);
            }
        }
        std::thread::sleep(std::time::Duration::from_secs(3));
    });
}

fn show_main(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.set_focus();
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let handle = app.handle().clone();
            let store = load_store(&handle);
            app.manage(AppState {
                store: Mutex::new(store),
                last_pending: Mutex::new(0),
            });
            app.manage(pty::PtyState::default());

            // Tray menu
            let open = MenuItem::with_id(app, "open", "Open Agents", true, None::<&str>)?;
            let refresh = MenuItem::with_id(app, "refresh", "Refresh", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &refresh, &sep, &quit])?;

            let _tray = TrayIconBuilder::with_id("main")
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .tooltip("Agents")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => show_main(app),
                    "refresh" => {
                        let _ = app.emit("refresh", ());
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            spawn_poller(handle);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            list_connections,
            set_active,
            upsert_connection,
            agentd_get,
            agentd_action,
            health,
            start_local_agentd,
            read_doc,
            write_doc,
            list_memory,
            pty_spawn,
            pty_write,
            pty_resize,
            pty_kill,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
