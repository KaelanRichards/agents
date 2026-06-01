# agents.env.zsh — env + PATH for EVERY zsh: interactive, login, AND the non-interactive
# shells that agents (Claude Code / Codex) spawn for their Bash tool. Source from ~/.zshenv.
#
# Keep this fast and side-effect-free: PATH/env only. Prompt, completions, and aliases are
# interactive concerns and live in agents.zsh (sourced from ~/.zshrc) instead.
#
# Why this file exists: zsh reads ~/.zshenv for every shell, but ~/.zprofile/~/.zshrc only for
# login/interactive ones. Putting the toolchain here is what makes `node`/`brew`/`rg`/`docker`
# resolve in agent-spawned shells — without it, agents must prefix every command with
# `eval "$(brew shellenv)"`.
#
# Idempotent by construction (re-prepends only when missing); NO exported sentinel — an
# exported guard leaks into child shells and would suppress setup before PATH is built.

# prepend a dir to PATH only if it exists and isn't already there (no duplicates)
_agents_path_prepend() { case ":${PATH}:" in *":$1:"*) ;; *) [ -d "$1" ] && PATH="$1:${PATH}" ;; esac; }

# Homebrew (macOS Apple Silicon or Linuxbrew) — skip the (slowish) eval if already on PATH
if ! command -v brew >/dev/null 2>&1; then
  for _b in /opt/homebrew/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
    [ -x "$_b" ] && eval "$("$_b" shellenv)" && break
  done
  unset _b
fi

_agents_path_prepend "$HOME/.local/bin"                    # agent helper scripts
_agents_path_prepend "$HOME/.local/share/mise/shims"       # node/pnpm/python (+ per-repo versions)
_agents_path_prepend "$HOME/.orbstack/bin"                 # OrbStack docker CLI (macOS)
_agents_path_prepend "/home/linuxbrew/.linuxbrew/share/google-cloud-sdk/bin" # gcloud components (Linuxbrew)
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"          # rustup / cargo

export PATH
unset -f _agents_path_prepend 2>/dev/null

# Host-local secrets. These files are gitignored and must be mode 0600. Keep them narrow:
# shared agent env gets only the service credentials intended for all local MCP clients.
for _agents_secret_env in \
  "$HOME/.config/agents-secrets/datadog.env" \
  "$HOME/.config/agents-secrets/slack-mcp.env"
do
  [ -f "$_agents_secret_env" ] || continue
  _agents_secret_mode="$(stat -f '%Lp' "$_agents_secret_env" 2>/dev/null || stat -c '%a' "$_agents_secret_env" 2>/dev/null || true)"
  if [ "$_agents_secret_mode" = "600" ]; then
    set -a
    . "$_agents_secret_env"
    set +a
  fi
done
unset _agents_secret_env _agents_secret_mode

# Agent telemetry: when the local OTel stack is marked on (`obs on` / `obs up`, or `serve` on the
# VM), stream Claude Code metrics/logs to it. Reaches the non-interactive shells agents spawn, so
# usage/cost accrues without a per-session opt-in. Safe no-op if the collector isn't running.
if [ -f "${AGENTS_HOME:-$HOME/.config/agents}/observability/.telemetry-on" ]; then
  export CLAUDE_CODE_ENABLE_TELEMETRY=1
  export OTEL_METRICS_EXPORTER=otlp
  export OTEL_LOGS_EXPORTER=otlp
  export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
  export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4317}"
  export OTEL_METRIC_EXPORT_INTERVAL="${OTEL_METRIC_EXPORT_INTERVAL:-10000}"
fi
