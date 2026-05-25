# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2"]
# ///
"""Smoke test for the shared personal-actions MCP facade."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp-servers" / "personal-actions" / "server.py"


def load_server():
    spec = importlib.util.spec_from_file_location("personal_actions_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    mod = load_server()
    with tempfile.TemporaryDirectory() as td:
        old_env = os.environ.copy()
        try:
            os.environ["AGENTS_HOME"] = td
            os.environ["PERSONAL_ACTIONS_DRY_RUN"] = "1"
            os.environ["PERSONAL_ACTIONS_WEBHOOK_TOKEN"] = "secret-test-token"
            os.environ["PERSONAL_ACTIONS_WEBHOOK_HMAC_SECRET"] = "hmac-secret"

            response = json.loads(
                mod.personal_slack_send_message(
                    channel="#ops",
                    text="token=secret-test-token authorization: Bearer secret-test-token",
                )
            )
            assert response["status"] == "dry_run"
            assert response["dry_run"] is True
            assert response["provider"] == "webhook"

            log_dir = pathlib.Path(td) / "assistant" / "logs" / "personal-actions"
            logs = list(log_dir.glob("*.jsonl"))
            assert logs, "expected audit log"
            log_text = logs[0].read_text(encoding="utf-8")
            assert "secret-test-token" not in log_text
            assert "[REDACTED]" in log_text

            headers = mod._webhook_headers(b'{"action":"health_check","payload":{}}')
            assert headers["Authorization"] == "Bearer secret-test-token"
            assert headers["X-Personal-Actions-Idempotency-Key"]
            assert headers["X-Personal-Actions-Signature"].startswith("v1=")
            assert abs(int(headers["X-Personal-Actions-Timestamp"]) - int(time.time())) < 5

            work_response = json.loads(
                mod.personal_gmail_send_email(
                    to="kaelan@vizcom.com",
                    subject="Work account smoke",
                    body="body",
                    account="work",
                )
            )
            assert work_response["status"] == "dry_run"

            print("personal-actions smoke OK")
        finally:
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    main()
