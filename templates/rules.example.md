---
# Path-scoped rule — loads only when the agent touches matching files, keeping
# global AGENTS.md lean. Copy to <repo>/.claude/rules/<topic>.md and edit `paths`.
paths:
  - "tests/**/*"
  - "**/*_test.*"
  - "**/*.test.*"
---

# Testing rules (example)
- Mock external APIs; never hit the network in unit tests.
- Always cover the error/edge path, not just the happy path.
- Name tests `test_<behavior>`; one assertion theme per test.
