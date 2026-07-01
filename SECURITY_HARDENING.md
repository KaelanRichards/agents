# Security Hardening Record

> Record of the local Mac and `agents` VM security review and hardening performed on 2026-05-25 PDT / 2026-05-26 UTC.

## Scope

- Local system: `Kaelans-MacBook-Pro-2.local`, macOS 26.5, Apple Silicon.
- VM: Hetzner server `agents`, public IPv4 `91.99.218.202`, Tailscale IP `100.84.252.93`, Tailscale DNS `agents.tailfae3a0.ts.net`.
- Agent control plane config under `~/.config/agents`.
- Local Vizcom development containers managed by `/Users/kaelan/code/vizcom/docker-compose.yml`.

## Changes Applied

### Local Docker service exposure

The local Vizcom Postgres and Redis containers were publishing on all host interfaces.

Updated `/Users/kaelan/code/vizcom/docker-compose.yml`:

- Postgres: `127.0.0.1:5432:5432`
- Redis: `127.0.0.1:6379:6379`

Recreated the affected containers:

```bash
docker compose up -d postgres redis
```

Verified:

```text
vizcom_pg      127.0.0.1:5432->5432/tcp
vizcom_redis   127.0.0.1:6379->6379/tcp
```

### Local SSH agent forwarding

Updated `/Users/kaelan/.ssh/config` so the `agents` host uses Tailscale instead of the public IPv4 address and no longer forwards the local SSH agent by default:

```sshconfig
Host agents
  HostName 100.84.252.93
  User kaelan
  ForwardAgent no
```

Added the matching Tailscale-IP host key to `/Users/kaelan/.ssh/known_hosts` after verifying it matched the public-IP SSH host key.

Use `ssh -A agents` only for a deliberate one-off session that needs agent forwarding, and prefer not to re-enable agent forwarding on this host.

### Hetzner cloud firewall

Created and applied Hetzner firewall `agents-tight` to server `agents`, then moved SSH access fully behind Tailscale:

- Allow inbound UDP `41641` from `0.0.0.0/0` and `::/0` for Tailscale direct connectivity.
- No inbound public TCP SSH rule remains.

Verified firewall:

```text
Firewall: agents-tight
Applied to: agents
Rules:
  in udp 41641 from 0.0.0.0/0 and ::/0
```

Important: SSH now depends on Tailscale. Keep at least one authenticated tailnet device available before changing Tailscale or VM networking. If break-glass public SSH is ever needed, add a temporary Hetzner firewall rule for TCP `22` from the current trusted IP only, then remove it after recovery.

### VM SSH hardening

Created `/etc/ssh/sshd_config.d/99-agent-hardening.conf` on `agents` and reloaded SSH:

```text
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
X11Forwarding no
AllowAgentForwarding no
```

Verified the file via SSH after reload. SSH access through `Host agents` works over Tailscale.


## Could Not Apply Non-Interactively

macOS application firewall and stealth mode still require the user's admin password. Run these manually in an interactive shell:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setstealthmode on
```

Verify:

```bash
/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
/usr/libexec/ApplicationFirewall/socketfilterfw --getstealthmode
```

Expected:

```text
Firewall is enabled. (State = 1)
Firewall stealth mode is on
```

## Verification Commands

```bash
docker ps --filter name=vizcom_pg --filter name=vizcom_redis --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}'
hcloud firewall describe agents-tight
ssh agents 'sudo -n cat /etc/ssh/sshd_config.d/99-agent-hardening.conf'
ssh agents 'ss -tuln | awk "NR==1 || /:22|:443|41641/"'
tailscale status
gitleaks detect --source /Users/kaelan/.config/agents --no-git --redact --verbose
agents-doctor
```

## Residual Risks

- SSH is no longer publicly reachable through the Hetzner firewall. This improves exposure but makes Tailscale availability the primary admin dependency.
- The local macOS firewall remains disabled until the interactive `sudo` commands above are run.
- Local dev services use known development credentials. They are now localhost-bound, but should not be exposed through tunnels or public Docker port mappings.
- The Mac reported no MDM enrollment via `profiles status -type enrollment`; this conflicts with the shared machine instructions and should be checked in System Settings or Rippling.

## Additional Tailscale Hardening To Consider

- Enable Tailscale SSH in the admin console and restrict SSH to the `agents` machine to the specific user/device identities that need it.
- Add ACL tags such as `tag:agent-vm` and use ACLs instead of broad user-to-device reachability.
- Require device approval for new tailnet devices.
- Enable tailnet lock if operationally acceptable.
- Review Tailscale Serve permissions so only the dashboard endpoint intended for tailnet use is exposed.
