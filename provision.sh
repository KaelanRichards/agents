#!/usr/bin/env bash
# provision.sh — spin up an always-on Hetzner VM and bootstrap the agent environment.
#
# Prereqs (on your laptop):
#   - hcloud CLI:        brew install hcloud
#   - Hetzner API token: console.hetzner.cloud → Security → API Tokens (Read & Write)
#                        export HCLOUD_TOKEN=...
#   - your SSH key added to GitHub (so the private repo clone works via agent forwarding)
#
# Run:  bash ~/.config/agents/provision.sh
# Destroy later:  hcloud server delete agents
#
# Tunables (env vars):
VM_NAME="${VM_NAME:-agents}"
VM_TYPE="${VM_TYPE:-cax11}" # ARM 2 vCPU / 4 GB (~€4/mo). Heavier: cax21. US/x86: cpx21
VM_IMAGE="${VM_IMAGE:-ubuntu-24.04}"
VM_LOCATION="${VM_LOCATION:-fsn1}" # cax (ARM) is EU-only: fsn1/nbg1/hel1. US x86: ash/hil
VM_USER="${VM_USER:-kaelan}"
AGENTS_REPO="${AGENTS_REPO:-git@github.com:KaelanRichards/agents.git}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519.pub}"

set -euo pipefail
die() {
	echo "error: $*" >&2
	exit 1
}

command -v hcloud >/dev/null || die "hcloud not found — brew install hcloud"
[ -n "${HCLOUD_TOKEN:-}" ] || die "HCLOUD_TOKEN not set — export it (console.hetzner.cloud → API Tokens)"
[ -f "$SSH_KEY" ] || die "SSH key not found: $SSH_KEY"
export HCLOUD_TOKEN
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -o UserKnownHostsFile="$HOME/.ssh/known_hosts")

KEY_NAME="${VM_NAME}-key"
echo "==> registering SSH key with Hetzner (idempotent)"
hcloud ssh-key describe "$KEY_NAME" >/dev/null 2>&1 ||
	hcloud ssh-key create --name "$KEY_NAME" --public-key-from-file "$SSH_KEY"

echo "==> writing cloud-init (creates user '$VM_USER', base packages)"
CLOUD_INIT="$(mktemp)"
trap 'rm -f "$CLOUD_INIT"' EXIT
cat >"$CLOUD_INIT" <<EOF
#cloud-config
users:
  - name: ${VM_USER}
    groups: [sudo]
    sudo: ['ALL=(ALL) NOPASSWD:ALL']
    ssh_authorized_keys:
      - $(cat "$SSH_KEY")
package_update: true
packages: [git, curl, zsh, build-essential, file, procps]
EOF

echo "==> creating server $VM_NAME ($VM_TYPE / $VM_IMAGE / $VM_LOCATION)"
if ! hcloud server describe "$VM_NAME" >/dev/null 2>&1; then
	hcloud server create --name "$VM_NAME" --type "$VM_TYPE" --image "$VM_IMAGE" \
		--location "$VM_LOCATION" --ssh-key "$KEY_NAME" --user-data-from-file "$CLOUD_INIT"
fi
IP="$(hcloud server ip "$VM_NAME")"
echo "==> server IP: $IP"

echo "==> waiting for SSH..."
for _ in $(seq 1 60); do
	ssh "${SSH_OPTS[@]}" "${VM_USER}@${IP}" true 2>/dev/null && break
	sleep 5
done

echo "==> waiting for cloud-init to finish..."
ssh "${SSH_OPTS[@]}" "${VM_USER}@${IP}" "cloud-init status --wait || true"

echo "==> cloning repo + bootstrapping (private clone uses your forwarded SSH key)"
ssh -A "${SSH_OPTS[@]}" "${VM_USER}@${IP}" \
	"GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=accept-new' git clone '$AGENTS_REPO' ~/.config/agents && bash ~/.config/agents/bootstrap.sh"

cat <<NEXT

✓ VM ready at ${IP}
Connect + start a persistent session:
  ssh ${VM_USER}@${IP}        # or: mosh ${VM_USER}@${IP}
  tmux new -s work            # detach: Ctrl-b d   ·   reattach: tmux attach -t work
Authenticate on the VM:  claude (/login) · codex login · gh auth login · set GITHUB_PAT
Destroy when done:  hcloud server delete ${VM_NAME}
NEXT
