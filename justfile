set shell := ["bash", "-cu"]

default:
    just --list

sync:
    mcp-sync
    agents-sync

doctor:
    agents-doctor

audit:
    skills-audit

skills-update:
    skills-update

mcp-update:
    mcp-update

hermes-sync:
    hermes-sync

# Verify Brewfile and flake.nix stay in sync — both list the shared CLI toolbelt.
check-toolbelt:
    toolbelt-diff

# Verify the per-repo agent-config convention across all project repos (read-only).
verify-repos:
    agents-verify

# One verdict over the whole control plane: internal health + per-repo convention.
# Read-only; catches the drift classes from the 2026-05-28 sync audit.
verify-all:
    agents-doctor
    toolbelt-diff
    bash tests/sync-roundtrip.sh
    gitleaks detect --source . --no-git --redact --verbose
    agents-verify

test:
    shellcheck -S error -x bin/* hooks/*.sh tests/*.sh bootstrap.sh provision.sh teardown.sh
    actionlint
    jq -e . mcp.json >/dev/null
    jq -e . skills.lock.json >/dev/null
    yq -e . stacks/windmill/docker-compose.yml >/dev/null
    for f in agents/*.json; do jq -e . "$f" >/dev/null; done
    ruff check .
    toolbelt-diff
    bash tests/sync-roundtrip.sh
    uv run --script tests/agent_system_contract.py
    uv run --script tests/agent_control_smoke.py
    uv run --script tests/bigquery_mcp_smoke.py
    uv run --script tests/personal_actions_smoke.py
    uv run --script tests/windmill_stack_smoke.py
    uv run --script tests/dash_smoke.py
    uv run --script tests/webdash_smoke.py
    uv run --script tests/prompt_injection_policy.py

secrets:
    gitleaks detect --source . --no-git --redact --verbose

ci-local: test secrets doctor

# Describe @, bookmark it, and push. Pass the bookmark name as `name`:
#   just push-changes name=my-bookmark
push-changes name='':
    @test -n "{{ name }}" || (echo "usage: just push-changes name=<bookmark>" >&2 && exit 2)
    jj describe -m "Update shared agent environment"
    jj bookmark set {{ name }} -r @
    jj git push --bookmark {{ name }}
