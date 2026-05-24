---
name: spec
description: Spec-driven development workflow. Use when starting a non-trivial feature or change — draft an executable spec before coding, then implement and verify against it.
---

# Spec-driven development

Before writing code for a non-trivial change: spec → implement → verify.

1. **Draft the spec** from `~/.config/agents/templates/SPEC.md`. Fill in outcomes,
   scope boundaries (in/out), constraints, prior decisions, a task breakdown with
   explicit file/interface boundaries, and verification criteria. Save as `SPEC.md`
   in the working dir or feature branch.
2. **Confirm** the spec with the user before implementing.
3. **Implement** task by task, keeping each task within its declared file boundaries.
4. **Verify** with the `reviewer` subagent — it reads `SPEC.md` + the diff and returns
   a gap report. Fix gaps and re-review until clean.
5. For independent tasks, run them in parallel isolated checkouts with `wt new <name>`.
