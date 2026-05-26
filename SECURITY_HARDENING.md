# Security Hardening Record

> Record of the local Mac and `agents` VM security review and hardening performed on 2026-05-25 PDT / 2026-05-26 UTC.

## Scope

- Local system: `Kaelans-MacBook-Pro-2.local`, macOS 26.5, Apple Silicon.
- VM: Hetzner server `agents`, public IPv4 `91.99.218.202`, Tailscale IP `100.84.252.93`.
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

Updated `/Users/kaelan/.ssh/config` so the `agents` host no longer forwards the local SSH agent by default:

```sshconfig
Host agents
  HostName 91.99.218.202
  User kaelan
  ForwardAgent no
```

Use `ssh -A agents` only for a deliberate one-off session that needs agent forwarding.

### Hetzner cloud firewall

Created and applied Hetzner firewall `agents-tight` to server `agents`:

- Allow inbound TCP `22` only from current public IP `98.207.58.134/32`.
- Allow inbound UDP `41641` from `0.0.0.0/0` and `::/0` for Tailscale direct connectivity.
- No public access to webdash; it remains localhost-bound and exposed through Tailscale Serve.

Verified firewall:

```text
Firewall: agents-tight
Applied to: agents
Rules:
  in tcp 22 from 98.207.58.134/32
  in udp 41641 from 0.0.0.0/0 and ::/0
```

Important: if the home/office public IP changes, SSH over the public address may stop working until this rule is updated. Tailscale access should continue as long as outbound networking works on both sides.

### VM SSH hardening

Created `/etc/ssh/sshd_config.d/99-agent-hardening.conf` on `agents` and reloaded SSH:

```text
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
X11Forwarding no
AllowAgentForwarding no
```

Verified the file via SSH after reload. Public SSH still accepted the existing key from the allowed IP.

### VM dashboard posture

Confirmed the dashboard remains bound locally and served through Tailscale:

```text
127.0.0.1:8787        webdash
100.84.252.93:443     tailscale serve
```

Confirmed `WEBDASH_TOKEN` is configured and `/home/kaelan/.config/agents/webdash.env` is mode `0600`.

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
ssh agents 'ss -tuln | awk "NR==1 || /:22|:443|:8787|41641/"'
gitleaks detect --source /Users/kaelan/.config/agents --no-git --redact --verbose
agents-doctor
```

## Residual Risks

- Public SSH exists, but is now restricted by Hetzner firewall to one IPv4 source. Keep Tailscale access working before changing SSH firewall rules further.
- The local macOS firewall remains disabled until the interactive `sudo` commands above are run.
- Local dev services use known development credentials. They are now localhost-bound, but should not be exposed through tunnels or public Docker port mappings.
- The Mac reported no MDM enrollment via `profiles status -type enrollment`; this conflicts with the shared machine instructions and should be checked in System Settings or Rippling.
