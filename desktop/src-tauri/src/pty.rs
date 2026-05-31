//! Embedded PTY sessions for the "Attach" feature.
//!
//! Spawns an interactive agent session (`agentp <profile>` locally, or `ssh <host> -t 'agentp …'`
//! for the remote VM) inside a real pseudo-terminal, streams its output to the frontend xterm.js
//! widget as `pty://output` events, and accepts keystrokes / resizes / kill from JS commands.
//!
//! The session registry is an `Arc<Mutex<…>>` so the blocking reader thread can remove its own
//! entry on EOF without reaching back into Tauri-managed state.

use std::collections::HashMap;
use std::io::{Read, Write};
use std::sync::{Arc, Mutex};

use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use serde::Serialize;
use tauri::{AppHandle, Emitter};

/// One live PTY: a writer handle (to send keystrokes) and the master (to resize).
struct Session {
    writer: Box<dyn Write + Send>,
    master: Box<dyn portable_pty::MasterPty + Send>,
}

type Sessions = Arc<Mutex<HashMap<String, Session>>>;

#[derive(Clone)]
pub struct PtyState {
    sessions: Sessions,
}

impl Default for PtyState {
    fn default() -> Self {
        PtyState {
            sessions: Arc::new(Mutex::new(HashMap::new())),
        }
    }
}

#[derive(Clone, Serialize)]
struct OutputEvent {
    id: String,
    chunk: String,
}

#[derive(Clone, Serialize)]
struct ExitEvent {
    id: String,
}

/// Build the shell command for a session. `host` empty → local `agentp <profile>`; otherwise an
/// ssh into that host running agentp. The profile is validated by agentp itself (it exits
/// non-zero on an unknown profile). A login shell (`zsh -l`) loads PATH/mise so `agentp` resolves.
fn agent_command(profile: &str, engine: &str, host: &str) -> (String, Vec<String>) {
    let codex_flag = if engine == "codex" { "--codex " } else { "" };
    let inner = format!("agentp {codex_flag}{}", shell_quote(profile));
    if host.is_empty() {
        ("/bin/zsh".into(), vec!["-lc".into(), inner])
    } else {
        (
            "ssh".into(),
            vec![
                "-tt".into(),
                host.to_string(),
                format!("zsh -lc {}", shell_quote(&inner)),
            ],
        )
    }
}

fn shell_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', r"'\''"))
}

/// Spawn a new attached session. Returns the session id.
#[allow(clippy::too_many_arguments)]
pub fn spawn(
    app: &AppHandle,
    state: &PtyState,
    id: String,
    profile: String,
    engine: String,
    host: String,
    cols: u16,
    rows: u16,
) -> anyhow::Result<String> {
    let pty_system = native_pty_system();
    let pair = pty_system.openpty(PtySize {
        rows: rows.max(1),
        cols: cols.max(1),
        pixel_width: 0,
        pixel_height: 0,
    })?;

    let (program, args) = agent_command(&profile, &engine, &host);
    let mut cmd = CommandBuilder::new(program);
    for a in &args {
        cmd.arg(a);
    }
    if let Ok(home) = std::env::var("HOME") {
        cmd.cwd(home);
    }

    let mut child = pair.slave.spawn_command(cmd)?;
    drop(pair.slave);

    let mut reader = pair.master.try_clone_reader()?;
    let writer = pair.master.take_writer()?;

    state.sessions.lock().unwrap().insert(
        id.clone(),
        Session {
            writer,
            master: pair.master,
        },
    );

    // Reader thread: stream output until EOF, then emit exit + drop the session from the registry.
    let app_r = app.clone();
    let id_r = id.clone();
    let sessions = state.sessions.clone();
    std::thread::spawn(move || {
        let mut buf = [0u8; 4096];
        loop {
            match reader.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    let chunk = String::from_utf8_lossy(&buf[..n]).to_string();
                    let _ = app_r.emit(
                        "pty://output",
                        OutputEvent {
                            id: id_r.clone(),
                            chunk,
                        },
                    );
                }
                Err(_) => break,
            }
        }
        let _ = child.wait();
        sessions.lock().unwrap().remove(&id_r);
        let _ = app_r.emit("pty://exit", ExitEvent { id: id_r.clone() });
    });

    Ok(id)
}

pub fn write_input(state: &PtyState, id: &str, data: &str) -> anyhow::Result<()> {
    let mut map = state.sessions.lock().unwrap();
    if let Some(s) = map.get_mut(id) {
        s.writer.write_all(data.as_bytes())?;
        s.writer.flush()?;
    }
    Ok(())
}

pub fn resize(state: &PtyState, id: &str, cols: u16, rows: u16) -> anyhow::Result<()> {
    let map = state.sessions.lock().unwrap();
    if let Some(s) = map.get(id) {
        s.master.resize(PtySize {
            rows: rows.max(1),
            cols: cols.max(1),
            pixel_width: 0,
            pixel_height: 0,
        })?;
    }
    Ok(())
}

pub fn kill(state: &PtyState, id: &str) {
    // Dropping the master + writer closes the PTY; the child gets SIGHUP and the reader thread
    // hits EOF, emits exit, and removes itself (this removal is the belt-and-suspenders path).
    state.sessions.lock().unwrap().remove(id);
}
