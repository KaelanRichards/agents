# 1Password Secret Custody For Agents

> Move shared agent-system credentials out of long-lived plaintext env files and into a narrow 1Password automation vault.

## Target State

Use a dedicated 1Password vault named `Agents System` for credentials owned by the shared local
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

1. Sign in to 1Password locally or create a read-only service account for the `Agents System` vault.
2. Create 1Password items and fields matching `assistant/1password/agents.1password.env.example`.
3. Create `~/.config/agents-secrets/agents.1password.env` with only `op://` references.
4. Run `agents-secrets-op-check`.
5. Convert one launcher at a time to run under `agents-secrets-op-run`.
6. Rotate migrated tokens after the new path is stable.
7. Remove the old plaintext value from the legacy env file after each consumer no longer needs it.

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

## Verification

Run:

```sh
agents-secrets-op-check
agents-doctor
gitleaks detect
```
