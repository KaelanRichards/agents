# 1Password Secret Custody For Agents

> Move shared agent-system credentials out of long-lived plaintext env files and into a narrow 1Password automation vault.

## Target State

Use a dedicated 1Password vault named `Kaelan-Agents` for credentials owned by the shared local
agents system. Keep app/runtime production secrets out of this vault unless the agents system owns
them.

The local machine may use an interactive 1Password account. Unattended hosts should use a
1Password service account scoped read-only to only this vault. The only unattended bootstrap secret
is `OP_SERVICE_ACCOUNT_TOKEN`, stored in:

```text
~/.config/agents-secrets/1password-bootstrap.env
```

That file must be mode `0600`.

## Files

- `assistant/1password/agents.1password.env.example` — non-secret template of `op://` references.
- `~/.config/agents-secrets/agents.1password.env` — local untracked reference file created from the template.
- `bin/agents-secrets-op-run` — runs a command through `op run --env-file`.
- `bin/agents-secrets-op-check` — reports 1Password readiness without printing secret values.

## Migration Order

1. Sign in to 1Password locally or create a read-only service account for the `Kaelan-Agents` vault.
2. Create 1Password items and fields matching `assistant/1password/agents.1password.env.example`.
3. Create `~/.config/agents-secrets/agents.1password.env` with only `op://` references.
4. Run `agents-secrets-op-check`.
5. Preview import from legacy env files with `agents-secrets-op-import`.
6. Create missing 1Password items with `agents-secrets-op-import --apply`.
7. Generate the local reference env with `agents-secrets-op-import --write-env`; this includes only
   items/fields found in legacy local env files so `op run` does not fail on optional future secrets.
8. Convert one launcher at a time to run under `agents-secrets-op-run`.
9. Rotate migrated tokens after the new path is stable.
10. Remove the old plaintext value from the legacy env file after each consumer no longer needs it.

## Boundaries

- Do not store raw secret values in the repo.
- Do not commit `~/.config/agents-secrets/*`.
- Do not grant service accounts access to personal/private/default shared vaults.
- Keep AWS app/runtime secrets in AWS Secrets Manager or their existing production store.
- Keep the Vizcom SRE agent denied from AWS secret values; 1Password is only for agent-owned
  bootstrap credentials.

## First Candidates

- `personal-actions.env`: webhook token, HMAC secret, Gmail OAuth client secrets, refresh tokens.
- `windmill-admin.env`: Windmill admin password.
- `windmill-oauth.env`: OAuth client secrets.
- `webdash.env`: dashboard token, if present.
- `HCLOUD_TOKEN`: Hetzner API token, if used for provision/teardown/status.

## Personal Actions Migration

`personal-actions-check` prefers `~/.config/agents-secrets/agents.1password.env` when present. If
1Password is unavailable in the current shell, it falls back to the legacy `personal-actions.env`
file. Set `AGENTS_SECRETS_DISABLE_1PASSWORD=1` to force the legacy path while debugging.

`personal-actions-mcp` intentionally stays on the legacy chmod-600 env file for now. It is a stdio
MCP server, so startup must not depend on interactive desktop-app 1Password integration. Move it to
1Password only after unattended service-account auth is available in every MCP runtime.

After the 1Password path is stable in every runtime, rotate the imported tokens and remove migrated
raw values from `personal-actions.env`.

## Verification

Run:

```sh
agents-secrets-op-check
agents-secrets-op-import
agents-secrets-op-smoke
agents-doctor
gitleaks detect
```
