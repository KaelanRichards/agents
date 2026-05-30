# Agents desktop app

A native macOS app (Tauri 2) that is the **primary** surface over the agent control plane —
folding in the role of `dash` / `agents-status` / `dashweb`, plus two things only a desktop app
does well: a **menubar/tray status pill** and **native notifications for the approval inbox**.

## Architecture

```
 Tauri app (Rust core + static web frontend)
   │  invoke() IPC  (token stays in Rust → macOS Keychain; no CORS)
   ▼
 agentd  (web/agentd.py — typed JSON + SSE; imports scripts/agent_control.py)
   │  local: 127.0.0.1:8788   │  remote: VM over tailscale (token-gated)
```

- **Rust core** (`src-tauri/src/lib.rs`): owns the token (Keychain via `keyring`), proxies every
  agentd call, runs a background poller that pushes snapshots to the UI and fires notifications
  when the approval inbox grows, renders the tray, and does allowlisted local file edits for the
  Config/Memory editors.
- **Frontend** (`dist/`): dependency-free static HTML/CSS/JS using the global `window.__TAURI__`
  API (`withGlobalTauri: true`) — no bundler, no `npm install` for the UI.

## Prerequisites

- Rust (`rustup`), Node + `pnpm` (via mise), `uv` — all already in this environment.
- The Tauri CLI: `pnpm install` here pulls `@tauri-apps/cli` into the workspace.
- `agentd` reachable: run `agentd` in another terminal, or click **Start local agentd** in-app.

## Run (dev)

```bash
cd ~/.config/agents/desktop
pnpm install            # one-time: Tauri CLI
pnpm icons              # regenerate icons (already committed)
pnpm tauri dev          # launches the app + tray
```

For a full app bundle / dmg and proper platform icons:

```bash
pnpm tauri icon dist-icon.png   # generate .icns/.ico + all sizes
pnpm tauri build
```

## Connections

The tray/rail switches between backends. Tokens are stored in the macOS Keychain (service
`dev.kaelan.agents`, account = connection name), never on disk in plaintext. To add the remote
VM: pick it in the switcher (or it is seeded as `local` by default) — the remote one points at
`https://<vm>.<tailnet>.ts.net` and needs `AGENTD_TOKEN` set where agentd runs on the VM.

## Verification boundary

Rust compiles via `cargo check`; the frontend is static and validated by load. A full GUI launch
(`pnpm tauri dev`) requires a desktop session and is the developer's step.
