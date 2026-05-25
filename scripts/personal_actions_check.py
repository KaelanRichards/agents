"""Check the configured personal-actions webhook without performing a write."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


def load_env_file() -> None:
    configured = os.environ.get("PERSONAL_ACTIONS_ENV_FILE", "").strip()
    if configured:
        path = Path(configured).expanduser()
    else:
        path = Path.home() / ".config" / "agents-secrets" / "personal-actions.env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def fail(message: str) -> int:
    print(f"personal-actions-check: {message}", file=sys.stderr)
    return 1


def main() -> int:
    load_env_file()
    url = os.environ.get("PERSONAL_ACTIONS_WEBHOOK_URL", "").strip()
    if not url:
        return fail("PERSONAL_ACTIONS_WEBHOOK_URL is not set")
    if not url.startswith("https://") and os.environ.get("PERSONAL_ACTIONS_ALLOW_HTTP") != "1":
        return fail("webhook URL must be https:// unless PERSONAL_ACTIONS_ALLOW_HTTP=1")

    payload = {
        "action": "health_check",
        "payload": {
            "client": "personal-actions-check",
            "ts": int(time.time()),
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "personal-actions-check/1",
        "X-Personal-Actions-Idempotency-Key": str(uuid4()),
    }
    token = os.environ.get("PERSONAL_ACTIONS_WEBHOOK_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    hmac_secret = os.environ.get("PERSONAL_ACTIONS_WEBHOOK_HMAC_SECRET", "").strip()
    if hmac_secret:
        timestamp = str(int(time.time()))
        signed = f"{timestamp}.".encode("utf-8") + body
        digest = hmac.new(hmac_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        headers["X-Personal-Actions-Timestamp"] = timestamp
        headers["X-Personal-Actions-Signature"] = f"v1={digest}"

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            response_body = response.read(100_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        response_body = exc.read(20_000).decode("utf-8", errors="replace")
        return fail(f"HTTP {exc.code}: {response_body}")
    except urllib.error.URLError as exc:
        return fail(f"request failed: {exc.reason}")

    print(f"personal-actions backend reachable: HTTP {response.status}")
    if response_body:
        print(response_body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
