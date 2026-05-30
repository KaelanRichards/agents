# Spec: Agents Desktop App

## Outcome
A native macOS app (Tauri 2) that becomes the **primary** surface over the agent control plane —
absorbing the day-to-day role of `dash` / `agents-status` and `dashweb`'s mutation controls — plus
two things only a desktop app does well:

- a **menubar/tray status pill** (VM up/down + cost, pending-approval count, ledger-chain health),
  always present; and
- **native notifications for the approval inbox**, so a queued agent that hits a live-write or a
  tainted-context mutation pings the OS and can be approved/rejected without context-switching.

It controls the **local** control plane and connects to the **remote always-on VM** over the
tailnet, switching between them from the rail/tray.

## Architecture
- **One backend: `agentd`** (`web/agentd.py`, FastAPI via uv). Imports `scripts/agent_control.py`
  as a library (no CLI text-scraping); serves typed JSON for snapshot/fleet/profiles/ledger/
  approvals/queue/evals/mcp and an SSE feed tailing `state/events.jsonl`. Mutations reuse
  `agent_control`'s tested CLI paths so the tamper-evident ledger + event stream fire identically.
  Same backend for the desktop app, `dashweb`, and the VM.
- **Boundary: `--json` + `state/events.jsonl`** (phase 1). Every `append_ledger` projects the
  transition onto an append-only event log; `agent-control --json` exposes the same data the daemon
  returns, so the human (CLI) and machine (app) surfaces never drift.
- **Client: Tauri 2** (`desktop/`). Rust core owns the token (macOS Keychain via `keyring`),
  proxies all agentd calls (token never reaches JS; no CORS), runs a background poller that emits
  live updates to the UI and fires OS notifications, renders the tray, and does allowlisted local
  file edits for the Config/Memory editors. Frontend is dependency-free static HTML/CSS/JS via the
  global `window.__TAURI__` API (no bundler).

## Scope
- **In:** `web/agentd.py` + `bin/agentd`; the `--json`/events boundary in `agent_control.py`; the
  `desktop/` Tauri tree; a `serve`/systemd path to run `agentd` on the VM behind tailscale; a smoke
  test; docs.
- **In:** Reuse of the existing auth posture (localhost bind, optional token, same-origin CSRF on writes).
- **Out:** Replacing Claude/Codex/Hermes; running agents *inside* the app (it stages-and-observes;
  the queue worker / `swarm` still execute agents); Windows/Linux packaging (macOS first); rewriting
  the Python control plane in Rust (it stays the tested source of truth).

## Constraints
- Canonical sources stay in `~/.config/agents`; runtime state stays gitignored under `state/`.
- The app must not weaken any boundary: mutations still flow through the broker/approval logic in
  `agent_control`; the ledger hash-chain stays intact; no auto-approval.
- Token in Keychain, never in JS or plaintext on disk; remote = tailnet + token.
- `agentd` binds 127.0.0.1 unless `AGENTD_HOST` + `AGENTD_TOKEN` are both set.

## Tasks
- [x] T1 — Control-plane boundary: `--json`, `snapshot`, `emit_event`/`events.jsonl`
- [x] T2 — `agentd` typed daemon + SSE + `bin/agentd`
- [x] T3 — Tauri shell: tray status pill, native approval notifications, Keychain token, conn switch
- [x] T4 — Panels: Fleet / Runs (live) / Approvals / Queue+Swarm
- [x] T5 — Config + memory editors (allowlisted local writes) + Sync
- [x] T6 — Remote VM (`serve`/systemd for agentd behind tailscale), smoke test, docs

## Verification
- `agent-control snapshot`; `agent-control --json {profile,ledger,approve,queue,eval} list` — done.
- `agentd` read endpoints + SSE (`ledger` event after an approval) + approve/reject/queue via
  `/api/action` + CSRF 403 — done (live + `tests/agentd_smoke.py`).
- `cd desktop/src-tauri && cargo check` — compiles clean (0 warnings).
- `node --check desktop/dist/app.js`; `ruff`; `shellcheck bin/serve bin/agentd`; `gitleaks` — clean.
- Full GUI launch (`cd desktop && pnpm install && pnpm tauri dev`) requires a desktop session and is
  the developer's step (not run in this headless environment).
