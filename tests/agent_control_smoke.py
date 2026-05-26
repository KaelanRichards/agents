"""Smoke tests for local agent control-plane CLIs."""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]


def run(cmd: list[str], env: dict[str, str]) -> str:
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return (proc.stdout + proc.stderr).strip()


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, "AGENTS_STATE": td, "AGENTS_HOME": str(ROOT)}

        run(["agent-profile", "validate"], env)
        run(["agent-eval", "list"], env)

        approval_id = run(["agent-approve", "request", "--kind", "smoke", "--summary", "smoke"], env)
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
        run(["agentq", "start", task_id, "--foreground"], env)
        tail = run(["agentq", "tail", task_id, "--lines", "5"], env)
        assert "smoke" in tail
        run(["agentq", "reconcile"], env)

        print("agent control smoke OK")


if __name__ == "__main__":
    main()
