# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2"]
# ///
"""Live webhook-delivery test for the personal-actions facade.

The dry-run smoke test (personal_actions_smoke.py) never exercises `_dispatch_webhook`, so the
actual HTTP delivery path — request shape, over-the-wire HMAC signing, success parsing, HTTP-error
surfacing, and the https-only guard — was untested. This stands up a throwaway localhost HTTP
server and drives a real write through it, asserting the contract a webhook backend depends on.
Hermetic: no network egress, no real Slack/Gmail/Calendar, isolated AGENTS_HOME/STATE.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import pathlib
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp-servers" / "personal-actions" / "server.py"
TOKEN = "secret-test-token"  # noqa: S105 — test fixture, not a real credential
HMAC_SECRET = "hmac-secret-fixture"  # noqa: S105
LEAK = "Bearer super-secret-should-be-redacted"  # noqa: S105


def load_server():
    spec = importlib.util.spec_from_file_location("personal_actions_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class Handler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    mode = "ok"  # "ok" -> 200 json; "error" -> 500 with a secret in the body

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        Handler.requests.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        if Handler.mode == "error":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"internal error: {LEAK}".encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true,"id":"evt_1"}')

    def log_message(self, *_args) -> None:  # silence the default stderr access log
        return


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(f"webhook-live FAILED: {name}")


def main() -> None:
    mod = load_server()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    old_env = os.environ.copy()
    try:
        with tempfile.TemporaryDirectory() as td:
            os.environ["AGENTS_HOME"] = td
            os.environ["AGENTS_STATE"] = td
            os.environ["PERSONAL_ACTIONS_DRY_RUN"] = "0"
            os.environ["PERSONAL_ACTIONS_LIVE"] = "1"
            os.environ["PERSONAL_ACTIONS_REQUIRE_APPROVAL"] = "0"
            os.environ["PERSONAL_ACTIONS_ALLOW_HTTP"] = "1"
            os.environ["PERSONAL_ACTIONS_WEBHOOK_URL"] = f"http://127.0.0.1:{port}/hook"
            os.environ["PERSONAL_ACTIONS_WEBHOOK_TOKEN"] = TOKEN
            os.environ["PERSONAL_ACTIONS_WEBHOOK_HMAC_SECRET"] = HMAC_SECRET

            # --- success path: a write is delivered as a signed POST and the 200 is surfaced. ---
            Handler.mode = "ok"
            Handler.requests.clear()
            resp = json.loads(
                mod.personal_slack_send_message(channel="#ops", text="ship it")
            )
            check("write delivered ok", resp["status"] == "ok")
            check("provider is webhook", resp["provider"] == "webhook")
            check("200 surfaced to caller", resp["result"]["status_code"] == 200)
            check("exactly one POST received", len(Handler.requests) == 1)

            req = Handler.requests[0]
            check("posted to webhook path", req["path"] == "/hook")
            sent = json.loads(req["body"])
            check("action framed", sent["action"] == "slack_send_message")
            check("channel forwarded", sent["payload"]["channel"] == "#ops")

            h = {k.lower(): v for k, v in req["headers"].items()}
            check("bearer token sent", h.get("authorization") == f"Bearer {TOKEN}")
            check(
                "idempotency key sent",
                bool(h.get("x-personal-actions-idempotency-key")),
            )
            sig = h.get("x-personal-actions-signature", "")
            ts = h.get("x-personal-actions-timestamp", "")
            check("signature is v1", sig.startswith("v1="))
            # Recompute the HMAC over exactly what the receiver would verify (ts + "." + raw body).
            expected = hmac.new(
                HMAC_SECRET.encode(),
                f"{ts}.".encode() + req["body"],
                hashlib.sha256,
            ).hexdigest()
            check(
                "over-the-wire HMAC verifies",
                hmac.compare_digest(sig, f"v1={expected}"),
            )

            # --- error path: an HTTP 500 surfaces as an error AND the leaked secret is redacted. ---
            Handler.mode = "error"
            Handler.requests.clear()
            err = json.loads(
                mod.personal_slack_send_message(channel="#ops", text="will fail")
            )
            check("HTTP 500 surfaced as error", err["status"] == "error")
            check("error mentions HTTP 500", "500" in err["result"]["error"])
            check(
                "leaked secret redacted in error",
                "super-secret-should-be-redacted" not in json.dumps(err),
            )

            audit = pathlib.Path(td) / "assistant" / "logs" / "personal-actions"
            log_text = "\n".join(p.read_text() for p in audit.glob("*.jsonl"))
            check("audit captured the delivery", "slack_send_message" in log_text)
            check(
                "audit redacts the leaked secret",
                "super-secret-should-be-redacted" not in log_text,
            )

            # --- https guard: a plain-http URL is refused unless ALLOW_HTTP is set. ---
            os.environ.pop("PERSONAL_ACTIONS_ALLOW_HTTP", None)
            Handler.mode = "ok"
            Handler.requests.clear()
            guarded = json.loads(
                mod.personal_slack_send_message(channel="#ops", text="blocked")
            )
            check("plain-http refused", guarded["status"] == "error")
            check(
                "https requirement explained",
                "https" in guarded["result"]["error"].lower(),
            )
            check("no POST sent when https-guarded", len(Handler.requests) == 0)

            print("personal-actions webhook-live OK")
    finally:
        httpd.shutdown()
        os.environ.clear()
        os.environ.update(old_env)


if __name__ == "__main__":
    main()
