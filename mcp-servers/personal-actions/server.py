# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2"]
# ///
"""personal-actions — narrow shared MCP facade for Slack/Gmail/Calendar actions."""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("personal-actions")

MAX_TEXT = 50_000
SECRET_PATTERNS = [
    re.compile(r"(?i)\b(authorization)\b\s*[:=]\s*(?:bearer\s+)?[^,\s}]+"),
    re.compile(r"(?i)\b(token|secret|api[_-]?key|password)\b\s*[:=]\s*[^,\s}]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),
]


class PersonalActionError(ValueError):
    """Expected user/configuration error."""


def _load_env_file() -> None:
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


_load_env_file()


def _agents_home() -> Path:
    return Path(os.environ.get("AGENTS_HOME", str(Path.home() / ".config/agents"))).expanduser()


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _provider() -> str:
    return os.environ.get("PERSONAL_ACTIONS_PROVIDER", "webhook").strip() or "webhook"


def _dry_run() -> bool:
    if "PERSONAL_ACTIONS_DRY_RUN" in os.environ:
        return _truthy(os.environ.get("PERSONAL_ACTIONS_DRY_RUN"))
    if _truthy(os.environ.get("PERSONAL_ACTIONS_LIVE")):
        return False
    if _provider() == "webhook" and os.environ.get("PERSONAL_ACTIONS_WEBHOOK_URL", "").strip():
        return False
    return True


def _redact_text(value: str) -> str:
    out = value
    for pattern in SECRET_PATTERNS:
        out = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]" if m.lastindex else "[REDACTED]", out)
    return out


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        redacted: dict[str, Any] = {}
        for key, value in obj.items():
            if re.search(r"(?i)(authorization|token|secret|api[_-]?key|password)", key):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(value)
        return redacted
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    if isinstance(obj, str):
        return _redact_text(obj)
    return obj


def _audit(action: str, payload: dict[str, Any], status: str, result: dict[str, Any] | None = None) -> None:
    log_dir = _agents_home() / "assistant" / "logs" / "personal-actions"
    log_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": _now(),
        "action": action,
        "provider": _provider(),
        "dry_run": _dry_run(),
        "status": status,
        "payload": _redact(payload),
        "result": _redact(result or {}),
    }
    path = log_dir / f"{datetime.now(UTC).date().isoformat()}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def _require(name: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise PersonalActionError(f"{name} is required")
    if len(value) > MAX_TEXT:
        raise PersonalActionError(f"{name} is too long")
    return value


def _optional(value: str = "") -> str:
    value = (value or "").strip()
    if len(value) > MAX_TEXT:
        raise PersonalActionError("input is too long")
    return value


def _split_csv(value: str = "") -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _bounded_int(name: str, value: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PersonalActionError(f"{name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise PersonalActionError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _account(value: str = "personal") -> str:
    value = (value or "personal").strip().lower()
    if value not in {"personal", "work"}:
        raise PersonalActionError("account must be 'personal' or 'work'")
    return value


def _json_response(action: str, status: str, payload: dict[str, Any], result: dict[str, Any] | None = None) -> str:
    return json.dumps(
        {
            "action": action,
            "status": status,
            "dry_run": _dry_run(),
            "provider": _provider(),
            "result": result or {},
        },
        indent=2,
        sort_keys=True,
    )


def _dispatch(action: str, payload: dict[str, Any]) -> str:
    try:
        if _dry_run():
            result = {"message": "dry run: no provider call performed"}
            _audit(action, payload, "dry_run", result)
            return _json_response(action, "dry_run", payload, result)

        if action == "gmail_create_draft" and _gmail_compose_configured_for(str(payload.get("account", "personal"))):
            result = _gmail_create_draft_local(payload)
            _audit(action, payload, "ok", result)
            return _json_response(action, "ok", payload, result)

        if action == "gmail_trash_email":
            result = _gmail_trash_email_local(payload)
            _audit(action, payload, "ok", result)
            return _json_response(action, "ok", payload, result)

        if action == "gmail_search_messages" and _gmail_modify_configured_for(str(payload.get("account", "personal"))):
            result = _gmail_search_messages_local(payload)
            _audit(action, payload, "ok", result)
            return _json_response(action, "ok", payload, result)

        if action == "gmail_get_message" and _gmail_modify_configured_for(str(payload.get("account", "personal"))):
            result = _gmail_get_message_local(payload)
            _audit(action, payload, "ok", result)
            return _json_response(action, "ok", payload, result)

        provider = _provider()
        if provider == "webhook":
            result = _dispatch_webhook(action, payload)
        elif provider == "google_workspace_cli":
            result = _dispatch_google_workspace_cli(action, payload)
        else:
            raise PersonalActionError(
                "unsupported PERSONAL_ACTIONS_PROVIDER; use webhook, google_workspace_cli, or set PERSONAL_ACTIONS_DRY_RUN=1"
            )
        _audit(action, payload, "ok", result)
        return _json_response(action, "ok", payload, result)
    except PersonalActionError as exc:
        result = {"error": str(exc)}
        _audit(action, payload, "error", result)
        return _json_response(action, "error", payload, result)
    except Exception as exc:  # noqa: BLE001
        result = {"error": f"unexpected error: {exc}"}
        _audit(action, payload, "error", result)
        return _json_response(action, "error", payload, result)


def _dispatch_webhook(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = os.environ.get("PERSONAL_ACTIONS_WEBHOOK_URL", "").strip()
    if not url:
        raise PersonalActionError("PERSONAL_ACTIONS_WEBHOOK_URL is required for webhook provider")
    if not url.startswith("https://") and not _truthy(os.environ.get("PERSONAL_ACTIONS_ALLOW_HTTP")):
        raise PersonalActionError("webhook URL must be https:// unless PERSONAL_ACTIONS_ALLOW_HTTP=1")

    body = json.dumps({"action": action, "payload": payload}, separators=(",", ":")).encode("utf-8")
    headers = _webhook_headers(body)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            text = resp.read(200_000).decode("utf-8", errors="replace")
            return {"status_code": resp.status, "body": _parse_json_or_text(text)}
    except urllib.error.HTTPError as exc:
        text = exc.read(50_000).decode("utf-8", errors="replace")
        raise PersonalActionError(f"webhook returned HTTP {exc.code}: {_redact_text(text)}") from exc
    except urllib.error.URLError as exc:
        raise PersonalActionError(f"webhook request failed: {exc.reason}") from exc


def _webhook_headers(body: bytes) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "personal-actions-mcp/1",
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
    return headers


def _parse_json_or_text(text: str) -> Any:
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _gmail_compose_configured() -> bool:
    return _gmail_compose_configured_for("personal")


def _gmail_prefix(kind: str, account: str) -> str:
    if kind not in {"COMPOSE", "MODIFY"}:
        raise PersonalActionError(f"unsupported Gmail OAuth kind: {kind}")
    if account == "work":
        return f"PERSONAL_WORK_GMAIL_{kind}"
    return f"PERSONAL_GMAIL_{kind}"


def _gmail_compose_configured_for(account: str) -> bool:
    prefix = _gmail_prefix("COMPOSE", account)
    return all(
        os.environ.get(name, "").strip()
        for name in [
            f"{prefix}_CLIENT_ID",
            f"{prefix}_CLIENT_SECRET",
            f"{prefix}_REFRESH_TOKEN",
        ]
    )


def _gmail_modify_configured_for(account: str) -> bool:
    prefix = _gmail_prefix("MODIFY", account)
    return all(
        os.environ.get(name, "").strip()
        for name in [
            f"{prefix}_CLIENT_ID",
            f"{prefix}_CLIENT_SECRET",
            f"{prefix}_REFRESH_TOKEN",
        ]
    )


def _gmail_compose_access_token(account: str) -> str:
    return _gmail_oauth_access_token(_gmail_prefix("COMPOSE", account), "Gmail compose")


def _gmail_modify_access_token(account: str) -> str:
    return _gmail_oauth_access_token(_gmail_prefix("MODIFY", account), "Gmail modify")


def _gmail_oauth_access_token(prefix: str, label: str) -> str:
    body = urllib.parse.urlencode(
        {
            "client_id": os.environ[f"{prefix}_CLIENT_ID"].strip(),
            "client_secret": os.environ[f"{prefix}_CLIENT_SECRET"].strip(),
            "refresh_token": os.environ[f"{prefix}_REFRESH_TOKEN"].strip(),
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        text = exc.read(20_000).decode("utf-8", errors="replace")
        raise PersonalActionError(f"{label} token refresh failed: {_redact_text(text)}") from exc
    token = str(data.get("access_token", "")).strip()
    if not token:
        raise PersonalActionError(f"{label} token refresh returned no access_token")
    return token


def _mime_message(to: str, subject: str, body: str, cc: list[str], bcc: list[str], html: bool) -> str:
    lines = [
        f"To: {to}",
        f"Subject: {subject}",
        f"Content-Type: {'text/html' if html else 'text/plain'}; charset=\"UTF-8\"",
        "",
        body,
    ]
    if cc:
        lines.insert(1, f"Cc: {', '.join(cc)}")
    if bcc:
        lines.insert(2 if cc else 1, f"Bcc: {', '.join(bcc)}")
    return "\r\n".join(lines)


def _base64_url(value: str) -> str:
    import base64

    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _gmail_create_draft_local(payload: dict[str, Any]) -> dict[str, Any]:
    account = _account(str(payload.get("account", "personal")))
    if not _gmail_compose_configured_for(account):
        raise PersonalActionError(f"Gmail compose OAuth is not configured for account '{account}'")
    raw = _base64_url(
        _mime_message(
            payload["to"],
            payload["subject"],
            payload["body"],
            payload.get("cc", []),
            payload.get("bcc", []),
            bool(payload.get("html")),
        )
    )
    req = urllib.request.Request(
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
        data=json.dumps({"message": {"raw": raw}}, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {_gmail_compose_access_token(account)}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return {"status_code": resp.status, "body": json.loads(resp.read().decode("utf-8", errors="replace"))}
    except urllib.error.HTTPError as exc:
        text = exc.read(20_000).decode("utf-8", errors="replace")
        raise PersonalActionError(f"Gmail draft failed: {_redact_text(text)}") from exc


def _gmail_trash_email_local(payload: dict[str, Any]) -> dict[str, Any]:
    account = _account(str(payload.get("account", "personal")))
    if not _gmail_modify_configured_for(account):
        raise PersonalActionError(
            f"Gmail modify OAuth is not configured for account '{account}'; run personal-actions-google-modify-auth"
        )
    message_id = urllib.parse.quote(str(payload["message_id"]).strip(), safe="")
    req = urllib.request.Request(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/trash",
        data=b"",
        method="POST",
        headers={"Authorization": f"Bearer {_gmail_modify_access_token(account)}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return {"status_code": resp.status, "body": json.loads(resp.read().decode("utf-8", errors="replace"))}
    except urllib.error.HTTPError as exc:
        text = exc.read(20_000).decode("utf-8", errors="replace")
        raise PersonalActionError(f"Gmail trash failed: {_redact_text(text)}") from exc


def _google_get_json(url: str, token: str, label: str) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return {"status_code": resp.status, "body": json.loads(resp.read().decode("utf-8", errors="replace"))}
    except urllib.error.HTTPError as exc:
        text = exc.read(20_000).decode("utf-8", errors="replace")
        raise PersonalActionError(f"{label} failed: {_redact_text(text)}") from exc


def _gmail_search_messages_local(payload: dict[str, Any]) -> dict[str, Any]:
    account = _account(str(payload.get("account", "personal")))
    if not _gmail_modify_configured_for(account):
        raise PersonalActionError(
            f"Gmail modify OAuth is not configured for account '{account}'; run personal-actions-google-modify-auth"
        )
    query = urllib.parse.urlencode(
        {
            "q": str(payload.get("query", "")).strip(),
            "maxResults": int(payload.get("max_results", 10)),
        }
    )
    return _google_get_json(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{query}",
        _gmail_modify_access_token(account),
        "Gmail search",
    )


def _gmail_get_message_local(payload: dict[str, Any]) -> dict[str, Any]:
    account = _account(str(payload.get("account", "personal")))
    if not _gmail_modify_configured_for(account):
        raise PersonalActionError(
            f"Gmail modify OAuth is not configured for account '{account}'; run personal-actions-google-modify-auth"
        )
    message_id = urllib.parse.quote(str(payload["message_id"]).strip(), safe="")
    params = {
        "format": str(payload.get("format", "metadata")).strip(),
        "metadataHeaders": str(payload.get("metadata_headers", "")).strip(),
    }
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value})
    return _google_get_json(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}?{query}",
        _gmail_modify_access_token(account),
        "Gmail get message",
    )


def _google_api_cmd() -> list[str]:
    script = _hermes_home() / "skills" / "productivity" / "google-workspace" / "scripts" / "google_api.py"
    if not script.exists():
        raise PersonalActionError(f"Google Workspace script not found at {script}")
    return [sys.executable, str(script)]


def _run_google(args: list[str]) -> dict[str, Any]:
    cmd = _google_api_cmd() + args
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise PersonalActionError(f"google_workspace_cli failed: {_redact_text(err or out or 'no output')}")
    return {"command": args, "output": _parse_json_or_text(out)}


def _dispatch_google_workspace_cli(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action == "gmail_send_email":
        args = ["gmail", "send", "--to", payload["to"], "--subject", payload["subject"], "--body", payload["body"]]
        if payload.get("html"):
            args.append("--html")
        return _run_google(args)
    if action == "calendar_create_event":
        args = [
            "calendar",
            "create",
            "--summary",
            payload["summary"],
            "--start",
            payload["start"],
            "--end",
            payload["end"],
        ]
        if payload.get("location"):
            args += ["--location", payload["location"]]
        if payload.get("attendees"):
            args += ["--attendees", ",".join(payload["attendees"])]
        return _run_google(args)
    raise PersonalActionError(
        f"{action} is not implemented by google_workspace_cli provider; use webhook provider for this tool"
    )


@mcp.tool()
def personal_slack_send_message(channel: str, text: str, thread_ts: str = "") -> str:
    """Send one Slack message to a channel, user, or conversation id."""
    payload = {
        "channel": _require("channel", channel),
        "text": _require("text", text),
        "thread_ts": _optional(thread_ts),
    }
    return _dispatch("slack_send_message", payload)


@mcp.tool()
def personal_gmail_create_draft(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    html: bool = False,
    account: str = "personal",
) -> str:
    """Create a Gmail draft with explicit recipients, subject, and body."""
    payload = {
        "account": _account(account),
        "to": _require("to", to),
        "subject": _require("subject", subject),
        "body": _require("body", body),
        "cc": _split_csv(cc),
        "bcc": _split_csv(bcc),
        "html": bool(html),
    }
    return _dispatch("gmail_create_draft", payload)


@mcp.tool()
def personal_gmail_send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    html: bool = False,
    account: str = "personal",
) -> str:
    """Send a Gmail email with explicit recipients, subject, and body."""
    payload = {
        "account": _account(account),
        "to": _require("to", to),
        "subject": _require("subject", subject),
        "body": _require("body", body),
        "cc": _split_csv(cc),
        "bcc": _split_csv(bcc),
        "html": bool(html),
    }
    return _dispatch("gmail_send_email", payload)


@mcp.tool()
def personal_gmail_trash_email(message_id: str, account: str = "personal") -> str:
    """Move one exact Gmail message id to Trash; does not permanently delete."""
    payload = {
        "account": _account(account),
        "message_id": _require("message_id", message_id),
    }
    return _dispatch("gmail_trash_email", payload)


@mcp.tool()
def personal_gmail_search_messages(query: str, max_results: int = 10, account: str = "personal") -> str:
    """Search Gmail messages by Gmail query syntax and return message ids/thread ids."""
    payload = {
        "account": _account(account),
        "query": _require("query", query),
        "max_results": _bounded_int("max_results", max_results, 1, 25),
    }
    return _dispatch("gmail_search_messages", payload)


@mcp.tool()
def personal_gmail_get_message(
    message_id: str,
    format: str = "metadata",
    metadata_headers: str = "From,To,Cc,Subject,Date",
    account: str = "personal",
) -> str:
    """Get one Gmail message by exact id; defaults to metadata/snippet rather than full body."""
    fmt = _require("format", format).lower()
    if fmt not in {"minimal", "metadata", "full", "raw"}:
        raise PersonalActionError("format must be minimal, metadata, full, or raw")
    payload = {
        "account": _account(account),
        "message_id": _require("message_id", message_id),
        "format": fmt,
        "metadata_headers": ",".join(_split_csv(metadata_headers)),
    }
    return _dispatch("gmail_get_message", payload)


@mcp.tool()
def personal_calendar_create_event(
    summary: str,
    start: str,
    end: str,
    calendar_id: str = "primary",
    description: str = "",
    location: str = "",
    attendees: str = "",
    account: str = "personal",
) -> str:
    """Create one Google Calendar event with ISO-8601 start and end times."""
    payload = {
        "account": _account(account),
        "calendar_id": _require("calendar_id", calendar_id),
        "summary": _require("summary", summary),
        "start": _require("start", start),
        "end": _require("end", end),
        "description": _optional(description),
        "location": _optional(location),
        "attendees": _split_csv(attendees),
    }
    return _dispatch("calendar_create_event", payload)


@mcp.tool()
def personal_calendar_update_event(
    event_id: str,
    calendar_id: str = "primary",
    summary: str = "",
    start: str = "",
    end: str = "",
    description: str = "",
    location: str = "",
    attendees: str = "",
    account: str = "personal",
) -> str:
    """Update one Google Calendar event by event id."""
    payload = {
        "account": _account(account),
        "calendar_id": _require("calendar_id", calendar_id),
        "event_id": _require("event_id", event_id),
        "summary": _optional(summary),
        "start": _optional(start),
        "end": _optional(end),
        "description": _optional(description),
        "location": _optional(location),
        "attendees": _split_csv(attendees),
    }
    if not any(payload[key] for key in ["summary", "start", "end", "description", "location", "attendees"]):
        raise PersonalActionError("at least one update field is required")
    return _dispatch("calendar_update_event", payload)


@mcp.tool()
def personal_calendar_list_events(
    time_min: str,
    time_max: str,
    calendar_id: str = "primary",
    query: str = "",
    max_results: int = 20,
    account: str = "personal",
) -> str:
    """List Google Calendar events in a time window; read-only."""
    payload = {
        "account": _account(account),
        "calendar_id": _require("calendar_id", calendar_id),
        "time_min": _require("time_min", time_min),
        "time_max": _require("time_max", time_max),
        "query": _optional(query),
        "max_results": _bounded_int("max_results", max_results, 1, 100),
    }
    return _dispatch("calendar_list_events", payload)


@mcp.tool()
def personal_slack_search_messages(query: str, max_results: int = 10) -> str:
    """Search Slack messages with Slack search syntax; read-only and scope-dependent."""
    payload = {
        "query": _require("query", query),
        "max_results": _bounded_int("max_results", max_results, 1, 25),
    }
    return _dispatch("slack_search_messages", payload)


@mcp.tool()
def personal_drive_search_files(query: str, max_results: int = 10, account: str = "personal") -> str:
    """Search Google Drive files using Drive query syntax; read-only and scope-dependent."""
    payload = {
        "account": _account(account),
        "query": _require("query", query),
        "max_results": _bounded_int("max_results", max_results, 1, 50),
    }
    return _dispatch("drive_search_files", payload)


if __name__ == "__main__":
    mcp.run()
