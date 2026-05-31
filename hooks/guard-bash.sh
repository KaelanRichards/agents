#!/usr/bin/env bash
# Shared PreToolUse(Bash) guard for Claude Code + Codex.
# Reads the hook JSON on stdin and denies clearly destructive or security-sensitive
# shell commands, forcing the human to run them manually (human-in-the-loop).
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
printf '%s' "$c" | grep -Eq '\brm\b +-[A-Za-z]*r[A-Za-z]* +(/|~|\$HOME)( |/?$)' &&
	deny "Blocked: recursive rm of /, ~ or \$HOME. Run it yourself if you truly intend to."
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

# --- remote code execution ---
printf '%s' "$c" | grep -Eiq '(curl|wget)\b[^|]*\| *(sudo +)?(bash|sh|zsh)\b' &&
	deny "Blocked: piping a remote script into a shell. Download, review, then run."

exit 0
