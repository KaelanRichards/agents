"""Smoke checks for the local Windmill personal-actions backend files."""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    compose = ROOT / "stacks" / "windmill" / "docker-compose.yml"
    env_example = ROOT / "stacks" / "windmill" / ".env.example"
    handler = ROOT / "assistant" / "windmill" / "personal_actions_handler.ts"
    for path in [compose, env_example, handler]:
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
    print("windmill stack smoke OK")


if __name__ == "__main__":
    main()
