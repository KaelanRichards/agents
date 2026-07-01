---
name: qa
description: Verify a change before commit/PR — run tests, lint, and a spec/diff review, then emit one gap report. Use after implementing a non-trivial change.
---

# QA / verify loop

Run all of these against the current change, then produce ONE consolidated gap report.

1. **Tests** — detect and run the suite (`just test` if a `justfile` defines it, else
   `pnpm test` / `pytest -q` / `cargo test`). Keep only failures.
2. **Lint/format** — for touched files: `ruff check` (Python), `biome check` (JS/TS),
   `shellcheck` (shell).
3. **Spec & diff review** — delegate to the `reviewer` subagent with `SPEC.md` (if present)
   and the diff (`jj diff` / `git diff`); collect its findings.

Report format:
- ❌ **Blockers** — failing tests, unmet spec requirements.
- ⚠️ **Warnings** — lint issues, missing tests, scope creep.
- ✅ **Verdict** — ready to commit, or fix blockers and re-run.

For projects with an eval suite, the CI counterpart is `templates/eval.yml`
(DeepEval/pytest regression gate on PRs).
