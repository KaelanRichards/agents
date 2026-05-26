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
import subprocess
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

            trash_response = json.loads(mod.personal_gmail_trash_email(message_id="gmail-message-id", account="work"))
            assert trash_response["action"] == "gmail_trash_email"
            assert trash_response["status"] == "dry_run"

            gmail_search_response = json.loads(
                mod.personal_gmail_search_messages(query='from:kaelan@vizcom.com newer_than:7d', account="work")
            )
            assert gmail_search_response["action"] == "gmail_search_messages"
            assert gmail_search_response["status"] == "dry_run"

            gmail_get_response = json.loads(
                mod.personal_gmail_get_message(message_id="gmail-message-id", account="work")
            )
            assert gmail_get_response["action"] == "gmail_get_message"
            assert gmail_get_response["status"] == "dry_run"

            calendar_response = json.loads(
                mod.personal_calendar_list_events(
                    time_min="2026-05-25T00:00:00-07:00",
                    time_max="2026-05-26T00:00:00-07:00",
                    account="work",
                )
            )
            assert calendar_response["action"] == "calendar_list_events"
            assert calendar_response["status"] == "dry_run"

            slack_search_response = json.loads(mod.personal_slack_search_messages(query="from:me"))
            assert slack_search_response["action"] == "slack_search_messages"
            assert slack_search_response["status"] == "dry_run"

            drive_response = json.loads(
                mod.personal_drive_search_files(query="name contains 'roadmap' and trashed = false", account="work")
            )
            assert drive_response["action"] == "drive_search_files"
            assert drive_response["status"] == "dry_run"

            os.environ["PERSONAL_ACTIONS_DRY_RUN"] = "0"
            os.environ["PERSONAL_ACTIONS_WEBHOOK_URL"] = "https://example.invalid/webhook"
            os.environ["PERSONAL_ACTIONS_REQUIRE_APPROVAL"] = "1"
            os.environ["AGENTS_HOME"] = str(ROOT)
            os.environ["AGENTS_STATE"] = td
            approval_response = json.loads(
                mod.personal_slack_send_message(channel="#ops", text="approval smoke")
            )
            assert approval_response["status"] == "approval_required"
            approval_id = approval_response["result"]["approval_id"]
            assert approval_id
            pending = subprocess.run(
                ["agent-approve", "list", "--status", "pending"],
                env=os.environ,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert pending.returncode == 0
            assert approval_id in pending.stdout

            print("personal-actions smoke OK")
        finally:
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    main()
