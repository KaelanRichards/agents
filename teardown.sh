#!/usr/bin/env bash
# teardown.sh — snapshot (optional) and delete the Hetzner agent VM to stop billing.
#
# Usage:
#   bash ~/.config/agents/teardown.sh                  # snapshot, then delete (asks to confirm)
#   bash ~/.config/agents/teardown.sh --no-snapshot    # full delete (uncommitted VM state lost)
#   bash ~/.config/agents/teardown.sh -y               # skip the confirmation prompt
#
# Restore later from a snapshot (already fully set up — no re-bootstrap needed):
#   hcloud image list --type snapshot
#   hcloud server create --name agents --type cax11 --location fsn1 \
#       --image <snapshot-id> --ssh-key agents-key
VM_NAME="${VM_NAME:-agents}"
SNAPSHOT=1
ASSUME_YES=0
set -euo pipefail
die() {
	echo "error: $*" >&2
	exit 1
}

for a in "$@"; do
	case "$a" in
	--no-snapshot) SNAPSHOT=0 ;;
	--snapshot) SNAPSHOT=1 ;;
	-y | --yes) ASSUME_YES=1 ;;
	*) die "unknown arg: $a (see header for usage)" ;;
	esac
done

command -v hcloud >/dev/null || die "hcloud not found — brew install hcloud"
[ -n "${HCLOUD_TOKEN:-}" ] || die "HCLOUD_TOKEN not set"
export HCLOUD_TOKEN
hcloud server describe "$VM_NAME" >/dev/null 2>&1 || die "no server named '$VM_NAME'"

IP="$(hcloud server ip "$VM_NAME" 2>/dev/null || echo '?')"
echo "About to tear down server '$VM_NAME' ($IP)."
if [ "$SNAPSHOT" = 1 ]; then
	echo "  - a restorable snapshot will be created first (small monthly cost)"
else
	echo "  - NO snapshot — full delete; any uncommitted VM state is lost"
fi

if [ "$ASSUME_YES" != 1 ]; then
	printf "Type the server name to confirm (%s): " "$VM_NAME"
	read -r reply
	[ "$reply" = "$VM_NAME" ] || die "confirmation did not match; aborting"
fi

if [ "$SNAPSHOT" = 1 ]; then
	ts="$(date +%Y%m%d-%H%M%S)"
	echo "==> creating snapshot 'agents-$ts' ..."
	hcloud server create-image --type snapshot --description "agents-$ts" "$VM_NAME"
fi

echo "==> deleting server '$VM_NAME' ..."
hcloud server delete "$VM_NAME"
echo "✓ done — server billing has stopped."
[ "$SNAPSHOT" = 1 ] && echo "Snapshots:  hcloud image list --type snapshot"
echo "Spin up a fresh one:  bash ~/.config/agents/provision.sh"
