"""Smoke tests for local agent control-plane CLIs."""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import importlib.util


ROOT = pathlib.Path(__file__).resolve().parents[1]


def run(cmd: list[str], env: dict[str, str]) -> str:
    proc = subprocess.run(
        cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return (proc.stdout + proc.stderr).strip()


def load_control():
    path = ROOT / "scripts" / "agent_control.py"
    spec = importlib.util.spec_from_file_location("agent_control", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, "AGENTS_STATE": td, "AGENTS_HOME": str(ROOT)}

        run(["agent-profile", "validate"], env)

        control = load_control()
        slack = control.broker_authorize(
            "personal-assistant",
            "personal-actions",
            "personal_slack_send_message",
            False,
        )
        assert slack["allowed"] is True
        assert slack["mutation"] is True
        assert slack["needs_confirmation"] is True

        unknown = control.broker_authorize(
            "personal-assistant", "personal-actions", "personal_unknown_read", False
        )
        assert unknown["allowed"] is False

        prod_write = control.broker_authorize(
            "prod-observer", "datadog", "create_monitor", False
        )
        assert prod_write["allowed"] is False
        assert prod_write["mutation"] is True
        assert prod_write["needs_confirmation"] is True

        print("agent control smoke OK")


if __name__ == "__main__":
    main()
