"""Smoke checks for the local Windmill personal-actions backend files."""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    compose = ROOT / "stacks" / "windmill" / "docker-compose.yml"
    env_example = ROOT / "stacks" / "windmill" / ".env.example"
    handler = ROOT / "assistant" / "windmill" / "personal_actions_handler.ts"
    oauth_example = ROOT / "assistant" / "windmill" / "oauth.env.example"
    oauth_configure = ROOT / "scripts" / "windmill_oauth_configure.py"
    link_resources = ROOT / "scripts" / "windmill_link_personal_resources.py"
    canary = ROOT / "scripts" / "personal_actions_canary.py"
    compose_auth = ROOT / "scripts" / "personal_actions_google_compose_auth.py"
    for path in [compose, env_example, handler, oauth_example, oauth_configure, link_resources, canary, compose_auth]:
        assert path.exists(), f"missing {path}"

    compose_text = compose.read_text(encoding="utf-8")
    assert "127.0.0.1:${WINDMILL_PORT:-8790}:8000" in compose_text
    assert "MODE: server" in compose_text
    assert "MODE: worker" in compose_text

    handler_text = handler.read_text(encoding="utf-8")
    for action in [
        "slack_send_message",
        "gmail_create_draft",
        "gmail_send_email",
        "calendar_create_event",
        "calendar_update_event",
    ]:
        assert action in handler_text
    assert "export async function main" in handler_text
    assert "x-personal-actions-signature" in handler_text
    assert "wmill.getVariable" in handler_text
    bootstrap = (ROOT / "scripts" / "windmill_bootstrap.py").read_text(encoding="utf-8")
    assert "jobs/run_wait_result/h" in bootstrap
    assert '"tag": "deno"' in bootstrap
    oauth_text = oauth_configure.read_text(encoding="utf-8")
    assert "/api/settings/instance_config" in oauth_text
    assert "GOOGLE_OAUTH_CLIENT_ID" in oauth_text
    assert "WINDMILL_SLACK_OAUTH_CLIENT_ID" in oauth_text
    assert "gmail_compose" in link_resources.read_text(encoding="utf-8")
    assert "PERSONAL_GMAIL_COMPOSE_REFRESH_TOKEN" in compose_auth.read_text(encoding="utf-8")
    assert "slack_self_target" in canary.read_text(encoding="utf-8")
    print("windmill stack smoke OK")


if __name__ == "__main__":
    main()
