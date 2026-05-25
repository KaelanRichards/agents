"""Configure local Windmill OAuth clients for personal-actions resources."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SECRETS_DIR = Path.home() / ".config" / "agents-secrets"
ADMIN_ENV = SECRETS_DIR / "windmill-admin.env"
OAUTH_ENV = SECRETS_DIR / "windmill-oauth.env"


class ApiError(RuntimeError):
    pass


def load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def request(
    method: str,
    base_url: str,
    path: str,
    token: str | None = None,
    body: object | None = None,
) -> tuple[int, str]:
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(f"{base_url}{path}", data=payload, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"{method} {path} failed: HTTP {exc.code}: {text}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"{method} {path} failed: {exc.reason}") from exc


def login(base_url: str, email: str, password: str) -> str:
    _, text = request("POST", base_url, "/api/auth/login", body={"email": email, "password": password})
    return text.strip()


def pair(env: dict[str, str], client_key: str, secret_key: str) -> tuple[str, str] | None:
    client_id = env.get(client_key, "").strip()
    secret = env.get(secret_key, "").strip()
    if not client_id and not secret:
        return None
    if not client_id or not secret:
        raise ValueError(f"{client_key} and {secret_key} must be set together")
    return client_id, secret


def provider_pairs(env: dict[str, str]) -> dict[str, tuple[str, str]]:
    google = pair(env, "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET")
    providers: dict[str, tuple[str, str]] = {}
    gmail = pair(env, "WINDMILL_GMAIL_OAUTH_CLIENT_ID", "WINDMILL_GMAIL_OAUTH_CLIENT_SECRET") or google
    gcal = pair(env, "WINDMILL_GCAL_OAUTH_CLIENT_ID", "WINDMILL_GCAL_OAUTH_CLIENT_SECRET") or google
    gdrive = pair(env, "WINDMILL_GDRIVE_OAUTH_CLIENT_ID", "WINDMILL_GDRIVE_OAUTH_CLIENT_SECRET") or google
    slack = pair(env, "WINDMILL_SLACK_OAUTH_CLIENT_ID", "WINDMILL_SLACK_OAUTH_CLIENT_SECRET")
    if gmail:
        providers["gmail"] = gmail
    if gcal:
        providers["gcal"] = gcal
    if gdrive:
        providers["gdrive"] = gdrive
    if slack:
        providers["slack"] = slack
    return providers


def redact_connects(connects: list[str], configured: list[str]) -> str:
    visible = [name for name in configured if name in connects]
    missing = [name for name in configured if name not in connects]
    parts = [f"visible={','.join(visible) if visible else '-'}"]
    if missing:
        parts.append(f"not_visible_yet={','.join(missing)}")
    return " ".join(parts)


def configure(args: argparse.Namespace) -> int:
    admin = load_env(ADMIN_ENV)
    oauth = load_env(args.env_file)
    base_url = args.base_url or admin.get("WINDMILL_BASE_URL") or os.environ.get("WINDMILL_BASE_URL", "http://localhost:8790")
    base_url = base_url.rstrip("/")
    workspace = args.workspace or admin.get("WINDMILL_WORKSPACE") or os.environ.get("WINDMILL_WORKSPACE", "personal")
    email = admin.get("WINDMILL_ADMIN_EMAIL") or os.environ.get("WINDMILL_ADMIN_EMAIL", "admin@windmill.dev")
    password = admin.get("WINDMILL_ADMIN_PASSWORD") or os.environ.get("WINDMILL_ADMIN_PASSWORD", "")
    if not password:
        raise ValueError(f"missing WINDMILL_ADMIN_PASSWORD in {ADMIN_ENV}")
    providers = provider_pairs(oauth)
    if not providers:
        raise ValueError(
            f"no OAuth providers found in {args.env_file}; copy assistant/windmill/oauth.env.example there first"
        )

    token = login(base_url, email, password)
    _, text = request("GET", base_url, "/api/settings/instance_config", token)
    config = json.loads(text)
    global_settings = config.setdefault("global_settings", {})
    oauths = global_settings.setdefault("oauths", {})
    for provider, (client_id, secret) in providers.items():
        oauths[provider] = {"id": client_id, "secret": secret}
    request("PUT", base_url, "/api/settings/instance_config", token, config)

    if "slack" in providers and not args.skip_workspace_slack:
        client_id, secret = providers["slack"]
        request(
            "POST",
            base_url,
            f"/api/w/{workspace}/workspaces/slack_oauth_config",
            token,
            {"slack_oauth_client_id": client_id, "slack_oauth_client_secret": secret},
        )

    _, text = request("GET", base_url, "/api/oauth/list_connects", token)
    connects = json.loads(text)
    configured = sorted(providers)
    print(f"Configured Windmill OAuth clients: {', '.join(configured)}")
    print(f"OAuth API visibility: {redact_connects(connects, configured)}")
    print("Next: open Resources -> Add resource and connect u/admin/slack, u/admin/gmail, u/admin/gcal, u/admin/gdrive.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=OAUTH_ENV)
    parser.add_argument("--base-url")
    parser.add_argument("--workspace")
    parser.add_argument("--skip-workspace-slack", action="store_true")
    args = parser.parse_args()
    return configure(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ApiError, ValueError) as exc:
        print(f"windmill-oauth-configure: {exc}", file=sys.stderr)
        raise SystemExit(1)
