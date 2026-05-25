# Personal Assistant Policy

Hermes is the personal assistant front door. `~/.config/agents` remains the source of truth for
agent config, MCP policy, skills, hooks, and verification.

## Allowed First-Pass Actions

Hermes may use the configured personal action MCP endpoint for:

- Slack: send messages.
- Gmail: create drafts and send emails.
- Google Calendar: create events and update events.

Hermes may also use the read-only `agents` MCP tools for repo status, logs, diffs, task discovery,
and MCP server listing.

## Boundaries

- Never delete Slack messages, Gmail messages/drafts, or calendar events.
- Never use broad filesystem, terminal, browser, payment, password-manager, or purchasing tools
  from Hermes without an explicit follow-up change to this policy.
- Confirm ambiguous recipients, channels, calendars, dates, or times before taking action.
- Draft creation may happen without a second confirmation when the user asks for a draft.
- For Gmail sends and Slack posts, include recipients/channel, subject when applicable, and final
  body in the assistant response before sending unless the user explicitly says to send/post
  immediately.
- Slack canaries must target the user's own Slack user id or self-DM only.
- Calendar creates/updates require explicit confirmation unless the user labels the request as a
  test/canary.
- For Calendar updates, identify the target event before updating it.
- Log material actions to `assistant/logs/YYYY-MM-DD.md` when practical.

## Tool Surface Rule

The remote personal action MCP endpoint must be constrained at the provider/dashboard level to
only the allowed actions above. Do not connect a broad "all apps/all actions" MCP endpoint to
Hermes.
