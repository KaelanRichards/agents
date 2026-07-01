# Preferences

> How Kaelan likes the agents to work (control plane, explicit config, no Claude auto-memory).

- Use the existing `~/.config/agents` repo as the control plane.
- Prefer explicit logs and reviewable config over ad hoc assistant state.
- Slack, Gmail, and Calendar writes are allowed for the personal-assistant profile when
  routed through the constrained personal action MCP endpoint.
- **Do not use Claude Code's built-in auto-memory.** It is disabled (`autoMemoryEnabled: false` in
  `~/.claude/settings.json`). Keep durable memory here in `assistant/memory/` instead — reviewable,
  jj-versioned config. Don't re-enable Claude auto-memory or write to its store.
