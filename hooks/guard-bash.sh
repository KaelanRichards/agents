#!/usr/bin/env bash
# Shared PreToolUse(Bash) guard for Claude Code + Codex.
# Reads the hook JSON on stdin and denies clearly destructive or security-sensitive
# shell commands, forcing the human to run them manually (human-in-the-loop).
#
# NOTE: this is a best-effort, high-signal DENYLIST, not a sandbox. An agent with shell
# access can always obfuscate past a regex; the real least-privilege boundary is the OS
# Bash sandbox (`agentp`) + the compiled per-profile deny list. The rules here close the
# common/obvious destructive idioms so a stray or injected command is stopped by default.
set -uo pipefail
# Portable PATH: Homebrew prefix differs (macOS vs linuxbrew). Detect at runtime.
for _brew in /opt/homebrew/bin /home/linuxbrew/.linuxbrew/bin /usr/local/bin; do
	[ -d "$_brew" ] && case ":$PATH:" in *":$_brew:"*) ;; *) PATH="$_brew:$PATH" ;; esac
done
unset _brew
export PATH

# Fail CLOSED if jq is missing — this is a security guard, not a best-effort hook.
# Emitting a permissionDecision=deny is the only way to keep the agent from racing past.
if ! command -v jq >/dev/null 2>&1; then
	printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"guard-bash: jq missing on PATH; security guard cannot evaluate. Install jq and retry."}}\n'
	exit 2
fi

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // .tool_input.cmd // empty' 2>/dev/null)
[ -z "$cmd" ] && exit 0
c=$(printf '%s' "$cmd" | tr '\n\t' '  ' | tr -s ' ')

deny() {
	printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":%s}}\n' \
		"$(printf '%s' "$1" | jq -R .)"
	exit 0
}

# --- destructive filesystem ---
# Recursive rm of a root/home target OR any subpath beneath it. Anchor with (/| |$) so that
# `rm -rf ~/code`, `rm -rf $HOME/.config/agents`, `rm -rf ${HOME}/x` are all caught — not only the
# bare root. Tolerate a leading `--` end-of-options separator before the path.
printf '%s' "$c" | grep -Eq '\brm\b +-[A-Za-z]*r[A-Za-z]* +(-- +)?(/|~|\$\{?HOME\}?)(/| |$)' &&
	deny "Blocked: recursive rm of /, ~ or \$HOME (or a subpath). Run it yourself if you truly intend to."
# Explicit denies for high-value home subtrees referenced via the expanded absolute path.
printf '%s' "$c" | grep -Eq '\brm\b +-[A-Za-z]*r[A-Za-z]* +(-- +)?'"$HOME"'/(\.config/agents|\.ssh|\.claude|\.codex|code)(/| |$)' &&
	deny "Blocked: recursive rm of a protected home subtree (.config/agents, .ssh, .claude, .codex, code)."
# Bulk deletion that sidesteps a bare `rm`.
printf '%s' "$c" | grep -Eq '\bfind\b[^|]*(-delete\b|-exec +rm\b)' &&
	deny "Blocked: bulk delete via find -delete / -exec rm. Run it yourself if intended."
printf '%s' "$c" | grep -Eq '\bshred\b +-[A-Za-z]*' &&
	deny "Blocked: shred. Run it yourself if you truly intend to destroy data."
printf '%s' "$c" | grep -Eq '\brm\b +-[A-Za-z]*r[A-Za-z]* +/(usr|etc|var|bin|sbin|System|Applications|Library|opt|private|cores)(/| |$)' &&
	deny "Blocked: recursive rm of a protected system path."
printf '%s' "$c" | grep -Eq '\brm\b[^|;]* /\*( |$)' &&
	deny "Blocked: rm of /*."
printf '%s' "$c" | grep -Eq ':\(\) *\{ *:\|' &&
	deny "Blocked: fork bomb."
printf '%s' "$c" | grep -Eq '\b(mkfs|newfs)\b|diskutil +(eraseDisk|eraseVolume|reformat)' &&
	deny "Blocked: disk formatting."
# Require a real device suffix so this matches actual block devices (sda, nvme0n1, vda, disk0,
# mmcblk0, loop0, rdisk0) without over-blocking lookalikes: digit-suffixed families (disk/nvme/
# mmcblk/loop) need a digit — so /dev/loopback is NOT a device write — and SCSI/virtio/Xen families
# (sd/vd/xvd) need a drive letter. (No legacy /dev/hd* — modern kernels don't use it, and it would
# false-match /dev/hdmi.)
printf '%s' "$c" | grep -Eq '\bdd\b[^|]* of=/dev/r?((disk|nvme|mmcblk|loop)[0-9]|(sd|vd|xvd)[a-z])' &&
	deny "Blocked: raw write to a block device."
printf '%s' "$c" | grep -Eq 'chmod +-R +0?777 +/( |$)' &&
	deny "Blocked: chmod -R 777 on /."

# --- managed-device protections (corporate Mac: SIP / SentinelOne / MDM) ---
printf '%s' "$c" | grep -Eiq 'csrutil +disable' &&
	deny "Blocked: disabling SIP on a managed device."
printf '%s' "$c" | grep -Eiq '(sentinelctl|sentinelagent|sentinelone)[^|]*(disable|unload|uninstall|kill|stop)' &&
	deny "Blocked: tampering with SentinelOne (managed security)."
printf '%s' "$c" | grep -Eiq '\bprofiles\b[^|]*(remove|delete| -D| -R)' &&
	deny "Blocked: removing MDM/configuration profiles."
printf '%s' "$c" | grep -Eiq 'launchctl +(unload|bootout)[^|]*(sentinel|rippling|mdm)' &&
	deny "Blocked: unloading managed security/MDM agents."

# --- remote code execution (best-effort: close the common fetch-and-exec idioms) ---
# 1) Classic pipe into a shell:  curl ... | bash   (incl. xh/aria2c as fetchers).
printf '%s' "$c" | grep -Eiq '(curl|wget|xh|aria2c)\b[^|]*\| *(sudo +)?(bash|sh|zsh|ksh|dash)\b' &&
	deny "Blocked: piping a remote fetch into a shell. Download, review, then run."
# 2) Process/command substitution feeding a shell or eval:  bash <(curl ..)  /  sh -c "$(curl ..)"  /  eval "$(wget ..)".
printf '%s' "$c" | grep -Eiq '\b(bash|sh|zsh|ksh|dash|eval)\b[^|]*[<$]\( *(sudo +)?(curl|wget|xh|aria2c)\b' &&
	deny "Blocked: fetch-and-exec via process/command substitution into a shell. Download, review, then run."
# 3) Any process/command substitution whose first token is a fetcher (catches the reverse ordering).
printf '%s' "$c" | grep -Eiq '[<$]\( *(sudo +)?(curl|wget|xh|aria2c)\b' &&
	deny "Blocked: fetch-and-exec via process/command substitution. Download, review, then run."

exit 0
