# Repository guide

This repository is a portable development environment, not an agent framework or control plane.

## Design constraints

- Prefer established upstream tools and their native configuration.
- chezmoi deploys user configuration; mise installs versioned command-line tools.
- Agent clients own their sandbox, approvals, OAuth, MCP, plugins, and runtime state.
- Keep the shared agent instructions short and platform-neutral.
- Put OS differences in chezmoi templates, .chezmoiignore, or the optional nix/ macOS layer.
- Do not add custom brokers, guards, MCP wrappers, schedulers, memory services, or orchestration without an explicit, measured need.
- Never put credentials or generated client state in this repository.

## Verification

Before finishing a change:

1. Run a chezmoi dry-run against a temporary destination.
2. Run mise install --dry-run with home/dot_config/mise/config.toml as the config.
3. Validate changed JSON, TOML, Nix, and GitHub Actions with their upstream tools when available.
4. Check jj diff and preserve unrelated work.
