"""Run live personal-actions canaries."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

SECRETS_DIR = Path.home() / ".config" / "agents-secrets"
PERSONAL_ENV = SECRETS_DIR / "personal-actions.env"
ADMIN_ENV = SECRETS_DIR / "windmill-admin.env"
SERVER = Path.home() / ".config" / "agents" / "mcp-servers" / "personal-actions" / "server.py"


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


def http_text(method: str, url: str, token: str | None = None, body: object | None = None) -> str:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=45) as resp:  # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


def http_json(method: str, url: str, token: str | None = None, body: object | None = None) -> object:
    text = http_text(method, url, token=token, body=body)
    return json.loads(text) if text else {}


def personal_dispatch(action: str, payload: dict[str, object]) -> dict[str, object]:
    env = load_env(PERSONAL_ENV)
    body = json.dumps({"action": action, "payload": payload}, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time()))
    sig = hmac.new(
        env["PERSONAL_ACTIONS_WEBHOOK_HMAC_SECRET"].encode("utf-8"),
        f"{ts}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    req = urllib.request.Request(
        env["PERSONAL_ACTIONS_WEBHOOK_URL"],
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {env['PERSONAL_ACTIONS_WEBHOOK_TOKEN']}",
            "X-Personal-Actions-Idempotency-Key": str(uuid4()),
            "X-Personal-Actions-Timestamp": ts,
            "X-Personal-Actions-Signature": f"v1={sig}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")


def windmill_resource_value(path: str) -> dict[str, object]:
    admin = load_env(ADMIN_ENV)
    base = admin["WINDMILL_BASE_URL"].rstrip("/")
    workspace = admin["WINDMILL_WORKSPACE"]
    token = http_text(
        "POST",
        f"{base}/api/auth/login",
        body={"email": admin["WINDMILL_ADMIN_EMAIL"], "password": admin["WINDMILL_ADMIN_PASSWORD"]},
    ).strip()
    encoded = urllib.parse.quote(path, safe="")
    value = http_json("GET", f"{base}/api/w/{workspace}/resources/get_value_interpolated/{encoded}", token=token)
    if not isinstance(value, dict):
        raise RuntimeError(f"resource {path} did not return an object")
    return value


def slack_self_target() -> str:
    slack = windmill_resource_value("u/admin/slack")
    token = str(slack.get("token") or slack.get("access_token") or "")
    auth = http_json("POST", "https://slack.com/api/auth.test", token=token, body={})
    if not isinstance(auth, dict) or not auth.get("ok"):
        raise RuntimeError(f"Slack auth.test failed: {auth}")
    return str(auth["user_id"])


def local_gmail_draft(email: str, stamp: str, account: str) -> None:
    spec = importlib.util.spec_from_file_location("personal_actions_server", SERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {SERVER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    response = json.loads(
        mod.personal_gmail_create_draft(
            to=email,
            subject=f"Personal actions canary draft - {stamp}",
            body="Canary draft from the shared personal-actions backend.",
            account=account,
        )
    )
    if response.get("status") != "ok":
        raise RuntimeError(f"Gmail draft canary failed: {response}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="perform real sends/posts/calendar writes")
    parser.add_argument("--email", default="kadokaelan@gmail.com")
    parser.add_argument("--account", choices=["personal", "work"], default="personal")
    args = parser.parse_args()
    if not args.yes:
        print("Refusing to run live canaries without --yes")
        return 2
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    start = (datetime.now(UTC) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=15)
    results: dict[str, str] = {}

    personal_dispatch(
        "slack_send_message",
        {"channel": slack_self_target(), "text": f"Personal actions canary to self - {stamp}", "thread_ts": ""},
    )
    results["slack_self"] = "ok"
    personal_dispatch(
        "gmail_send_email",
        {
            "account": args.account,
            "to": args.email,
            "subject": f"Personal actions canary send - {stamp}",
            "body": "Canary send from the shared personal-actions backend.",
            "cc": [],
            "bcc": [],
            "html": False,
        },
    )
    results["gmail_send"] = "ok"
    created = personal_dispatch(
        "calendar_create_event",
        {
            "account": args.account,
            "calendar_id": "primary",
            "summary": f"Personal actions canary - {stamp}",
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
            "description": "Canary event from the shared personal-actions backend.",
            "location": "",
            "attendees": [],
        },
    )
    results["calendar_create"] = "ok"
    event_id = created.get("result", {}).get("id")
    personal_dispatch(
        "calendar_update_event",
        {
            "account": args.account,
            "calendar_id": "primary",
            "event_id": event_id,
            "summary": f"Personal actions canary updated - {stamp}",
            "start": "",
            "end": "",
            "description": "Updated canary event from the shared personal-actions backend.",
            "location": "",
            "attendees": [],
        },
    )
    results["calendar_update"] = "ok"
    env = load_env(PERSONAL_ENV)
    compose_key = "PERSONAL_WORK_GMAIL_COMPOSE_REFRESH_TOKEN" if args.account == "work" else "PERSONAL_GMAIL_COMPOSE_REFRESH_TOKEN"
    if env.get(compose_key):
        local_gmail_draft(args.email, stamp, args.account)
        results["gmail_draft"] = "ok"
    else:
        results["gmail_draft"] = "skipped_missing_compose_auth"
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"personal-actions-canary: {exc}", file=sys.stderr)
        raise SystemExit(1)
