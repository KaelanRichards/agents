# Spec: Harden MCP client configuration and health diagnostics

## Outcome
Codex and Claude can receive different MCP definitions from the same canonical source, including
client-specific `enabled` state, without host-local workarounds replacing the shared definition.
`mcp-auth status` reports the effective overlay-aware configuration without launching clients or
browser OAuth. A bounded, side-effect-free `mcp-auth health` command classifies MCPs as ready,
authentication-required, disabled, unverified, or broken without starting an MCP bridge or opening
a browser.

## Scope
- **In:** Add documented `clients.claude` / `clients.codex` overrides to MCP server definitions;
  deep-merge `mcp.local.json`; preserve Codex `enabled`; render and validate per-client effective
  configs; encode the Datadog and Cloudflare Codex compatibility overrides canonically; make
  `mcp-auth status` overlay-aware and non-probing; add a bounded MCP health preflight with machine-
  readable output; surface its static verdict in `agents-doctor`; update contracts, tests, and docs.
- **Out (explicitly not doing):** Authenticate Cloudflare or any other provider; read, export, or
  copy OAuth secrets; migrate Linear/Sentry/Notion/Granola/Slack away from `mcp-remote`; reduce their
  60-second runtime timeouts; perform mutating MCP calls; change Vizcom application code.

## Constraints
- `mcp.json` remains canonical and `mcp.local.json` remains an optional gitignored host overlay.
- A `clients.<client>` object containing `type` is a full client definition; one without `type` is a
  partial override of the shared definition (for example `{ "enabled": false }`).
- Overlay object fields merge recursively while arrays replace; client definitions are resolved
  only after canonical + host overlay composition.
- Generated Claude JSON must not receive Codex-only keys such as `enabled`, startup/tool timeouts,
  or the internal `clients` object. Generated Codex TOML must retain supported policy keys.
- Health checks may perform bounded read-only HTTP discovery/preflight but must never launch
  `npx`, Claude, Codex, an MCP stdio process, or a browser. Client-managed OAuth stores are not read;
  their credential state is reported as unverified when it cannot be established safely.
- Preserve the no-token-copying contract and never print credential values.
- Use jq/yq serializers, ruff/formatting conventions, and the existing `just` verification tasks.

## Prior decisions / context
- OpenAI Codex supports native Streamable HTTP OAuth, server `enabled`, and bounded startup/tool
  timeouts in `~/.codex/config.toml`.
- Datadog currently requires a Codex-only base-resource URL because Codex rejects its toolset query
  URL during protected-resource metadata validation.
- Cloudflare's `mcp-remote` bridge requested unsupported OIDC scopes and repeatedly opened a
  browser; native Codex HTTP avoids that bridge behavior.
- The existing `mcp-auth status` reads only canonical metadata and executes live client probes,
  causing stale reports and roughly 38 seconds of timeouts in the observed environment.

## Tasks
- [x] T1 — Resolve per-client MCP definitions and Codex `enabled` output; add sync round-trip tests
  and canonical Datadog/Cloudflare client overrides — files: `bin/mcp-sync`, `mcp.json`,
  `tests/sync-roundtrip.sh`, `tests/agent_system_contract.py`.
- [x] T2 — Make auth status effective-config-aware and side-effect-free; add bounded health output
  and focused tests — files: `scripts/mcp_auth.py`, `mcp.auth.json`, `tests/mcp_auth_health.py`,
  `tests/agent_system_contract.py`.
- [x] T3 — Surface static health in the main doctor and document the schema/runbook — files:
  `bin/agents-doctor`, `README.md`, `justfile`.
- [x] T4 — Run formatting, focused tests, full local verification, reviewer diff-vs-spec review,
  and commit the verified change — files: verification-only plus any task-owned gap fixes.

## Verification
- `shellcheck -S error -x bin/mcp-sync bin/agents-doctor tests/sync-roundtrip.sh`
- `ruff check scripts/mcp_auth.py tests/mcp_auth_health.py`
- `ruff format --check scripts/mcp_auth.py tests/mcp_auth_health.py`
- `bash tests/sync-roundtrip.sh`
- `uv run --script tests/mcp_auth_health.py`
- `uv run --script tests/agent_system_contract.py`
- `mcp-sync check` shows distinct effective Claude/Codex definitions with Codex-native Datadog and
  Cloudflare while the shared definitions remain intact.
- `mcp-auth status cloudflare datadog` performs no client/bridge launch and reports the effective
  client transports.
- `mcp-auth health --client codex --offline` completes without network/browser/process launches and
  produces a nonzero exit only for broken entries.
- `just ci-local` passes, aside from explicitly documented pre-existing external-auth warnings.
- Reviewer confirms the implementation matches this spec with no token exposure or scope creep.
