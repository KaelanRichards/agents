# Spec: `verify-all` — one command that checks the whole agent control plane stays in sync

## Outcome
`just verify-all` (run from `~/.config/agents`) returns a single pass/fail verdict over
both the control plane's internal health AND the per-repo agent-config convention across
all project repos. It would have caught every drift item the 2026-05-28 sync audit found:
non-executable hooks, brain repos with a standalone `CLAUDE.md` and no `AGENTS.md` symlink,
and any committed `settings.local.json`. Read-only; mutates nothing.

## Scope
- **In:**
  - `agents-link --check [-C path]` — verify-only mode reusing the convention `agents-link` enforces.
  - `bin/agents-verify` — sweep project repos under `~/code` (+ the control plane), per repo assert:
    1. `AGENTS.md` is a real (non-symlink) file.
    2. `CLAUDE.md` is a symlink → `AGENTS.md` (fail on missing or on a standalone real file).
    3. every non-`test-*` hook script in `.claude/hooks/` is executable.
    4. if `.claude/settings.local.json` exists, it is git-ignored.
  - `just verify-all` — fan out existing leaf checks (`agents-doctor`, `toolbelt-diff`,
    `tests/sync-roundtrip.sh`, `gitleaks`) + `agents-verify`, aggregate to one exit code.
  - `tests/agents_verify_smoke.sh` — smoke test in an isolated tmp tree (good repo passes,
    each drift variant fails), matching the existing `tests/*.sh` isolation pattern.
- **Out (explicitly not doing):** auto-fixing drift (verify-all only reports; `agents-link`
  without `--check` remains the fixer); checking `*-workspaces` jj/swarm containers; changing
  the existing `test` / `ci-local` targets.

## Constraints
- Bash, `set -euo pipefail`, `shellcheck -S error` clean (matches `just test`).
- Discovery-based repo list (any `~/code/*` with `.claude/` or `AGENTS.md`, skipping
  `*-workspaces`) so new repos are covered automatically.
- Parseable, aligned output; non-zero exit on any failure; never mutate.

## Prior decisions / context
- Convention is defined by `bin/agents-link` (AGENTS.md real, CLAUDE.md → AGENTS.md). `--check`
  reuses it so there is one source of truth for "what the convention is."
- vizcom/vizcom-review already follow the convention; the 3 brain repos were converged in this
  session (CLAUDE.md symlinks created). `settings.local.json` is present+ignored in vizcom,
  absent elsewhere → invariant is "if present, must be ignored," not "must exist."

## Tasks
- [x] T1 — add `--check` mode to `agents-link` — files: `bin/agents-link`
- [x] T2 — `agents-verify` cross-repo convention sweep — files: `bin/agents-verify`
- [x] T3 — `verify-all` target — files: `justfile`
- [x] T4 — isolated smoke test — files: `tests/agents_verify_smoke.sh`

## Verification
- `shellcheck -S error bin/agents-link bin/agents-verify tests/agents_verify_smoke.sh` clean.
- `bash tests/agents_verify_smoke.sh` passes (good tree passes; each drift variant fails).
- `just verify-all` runs green against the live tree now that the brain repos are converged.
- `reviewer` subagent confirms the diff matches this spec with no scope creep.
