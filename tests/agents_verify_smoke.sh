#!/usr/bin/env bash
# agents_verify_smoke — assert agents-verify PASSES a correct repo and FAILS each
# drift variant. Builds throwaway repos under an isolated tmp tree; never touches
# live config.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
cleanup() { rm -rf -- "${tmp:?}"; }
trap cleanup EXIT

export PATH="$repo/bin:$PATH"

# make_repo <name> -> path to a fresh git repo with the correct convention.
make_repo() {
	local d="$tmp/$1"
	mkdir -p "$d/.claude/hooks"
	git -C "$d" init -q
	printf '# instructions\n' >"$d/AGENTS.md"
	ln -s AGENTS.md "$d/CLAUDE.md"
	printf '#!/usr/bin/env bash\n' >"$d/.claude/hooks/guard.sh"
	chmod +x "$d/.claude/hooks/guard.sh"
	printf 'test only\n' >"$d/.claude/hooks/test-helper.sh" # non-exec test-* must be tolerated
	echo "$d"
}

pass() { echo "ok: $1"; }
die() {
	echo "FAIL: $1" >&2
	exit 1
}

# 1. Correct repo passes.
good="$(make_repo good)"
agents-verify "$good" >/dev/null || die "correct repo should pass"
pass "correct repo passes"

# 2. Missing CLAUDE.md symlink fails.
r="$(make_repo no-link)"
rm "$r/CLAUDE.md"
if agents-verify "$r" >/dev/null 2>&1; then die "missing CLAUDE.md symlink should fail"; fi
pass "missing CLAUDE.md symlink fails"

# 3. Standalone real CLAUDE.md fails.
r="$(make_repo real-claude)"
rm "$r/CLAUDE.md"
printf '# standalone\n' >"$r/CLAUDE.md"
if agents-verify "$r" >/dev/null 2>&1; then die "standalone real CLAUDE.md should fail"; fi
pass "standalone real CLAUDE.md fails"

# 4. Non-executable hook fails.
r="$(make_repo bad-hook)"
chmod 644 "$r/.claude/hooks/guard.sh"
if agents-verify "$r" >/dev/null 2>&1; then die "non-executable hook should fail"; fi
pass "non-executable hook fails"

# 5. Committed (non-ignored) settings.local.json fails.
r="$(make_repo leaky-local)"
printf '{}\n' >"$r/.claude/settings.local.json"
if agents-verify "$r" >/dev/null 2>&1; then die "non-ignored settings.local.json should fail"; fi
pass "non-ignored settings.local.json fails"

# 6. settings.local.json that IS git-ignored passes.
r="$(make_repo ignored-local)"
printf '.claude/settings.local.json\n' >"$r/.gitignore"
printf '{}\n' >"$r/.claude/settings.local.json"
agents-verify "$r" >/dev/null || die "git-ignored settings.local.json should pass"
pass "git-ignored settings.local.json passes"

# --- Control-plane branch (global ~/.claude + ~/.codex symlinks, no repo-local CLAUDE.md) ---
# Isolate via AGENTS_HOME + HOME so the default (no-arg) repo set targets a throwaway tree.
cp="$tmp/cp"
mkdir -p "$cp" "$tmp/home/.claude" "$tmp/home/.codex" "$tmp/empty"
printf '# canonical\n' >"$cp/AGENTS.md"
make_cp_links() {
	ln -sf "$cp/AGENTS.md" "$tmp/home/.claude/CLAUDE.md"
	ln -sf "$cp/AGENTS.md" "$tmp/home/.codex/AGENTS.md"
}
run_cp() { env HOME="$tmp/home" AGENTS_HOME="$cp" AGENTS_CODE_ROOT="$tmp/empty" agents-verify; }

# 7. Correct control plane (both global links present) passes; no local CLAUDE.md required.
make_cp_links
[ -e "$cp/CLAUDE.md" ] && die "control plane must not require a local CLAUDE.md"
run_cp >/dev/null || die "correct control plane should pass"
pass "control plane with global symlinks passes (no local CLAUDE.md)"

# 8. Missing ~/.codex global link fails.
rm "$tmp/home/.codex/AGENTS.md"
if run_cp >/dev/null 2>&1; then die "missing ~/.codex global link should fail"; fi
pass "control plane missing a global symlink fails"

# 9. Global link pointing elsewhere fails.
make_cp_links
ln -sf "$tmp/elsewhere/AGENTS.md" "$tmp/home/.claude/CLAUDE.md"
if run_cp >/dev/null 2>&1; then die "global link to wrong target should fail"; fi
pass "control plane global symlink to wrong target fails"

echo "agents_verify_smoke: all checks passed"
