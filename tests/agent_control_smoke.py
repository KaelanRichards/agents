"""Smoke tests for local agent control-plane CLIs."""

from __future__ import annotations

import os
import pathlib
import shutil
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
        run(["agent-eval", "list"], env)

        approval_id = run(
            ["agent-approve", "request", "--kind", "smoke", "--summary", "smoke"], env
        )
        assert approval_id
        run(["agent-approve", "approve", approval_id, "--note", "test"], env)
        assert "approved" in run(["agent-approve", "list", "--status", "all"], env)

        task_id = run(
            [
                "agentq",
                "add",
                "--repo",
                str(ROOT),
                "--profile",
                "plan-readonly",
                "--agent",
                "noop",
                "--timeout",
                "30",
                "--max-attempts",
                "2",
                "--task",
                "smoke",
            ],
            env,
        )
        run(["agentq", "cancel", task_id], env)
        run(["agentq", "retry", task_id], env)
        # agentq start spins up a jj workspace; only exercise that path where jj AND a jj repo are
        # available. The CI lint job runs a plain-git checkout without jj — add/cancel/retry above
        # are DB-only and still covered there; the workspace lifecycle is covered locally / in the
        # full-toolbelt jobs.
        jj_repo = (
            bool(shutil.which("jj"))
            and subprocess.run(
                ["jj", "-R", str(ROOT), "root"],
                capture_output=True,
                cwd=ROOT,
            ).returncode
            == 0
        )
        if jj_repo:
            run(["agentq", "start", task_id, "--foreground"], env)
            tail = run(["agentq", "tail", task_id, "--lines", "5"], env)
            assert "smoke" in tail
            run(["agentq", "reconcile"], env)
        else:
            print("agent control smoke: skipping agentq workspace start (no jj repo)")

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
