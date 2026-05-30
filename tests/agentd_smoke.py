# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi>=0.110", "uvicorn>=0.30"]
# ///
"""Smoke checks for agentd: auth helpers, action routing, and the read model.

Loads web/agentd.py as a module (which imports scripts/agent_control.py) and asserts the
security-relevant behavior without booting a server: token gate, CSRF gate, unknown-action
rejection, and that the typed read model returns the expected shapes.
"""

from __future__ import annotations

import importlib.util
import pathlib
from types import SimpleNamespace

from fastapi import HTTPException

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_agentd():
    path = ROOT / "web" / "agentd.py"
    spec = importlib.util.spec_from_file_location("agentd", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def request(headers: dict[str, str], cookies: dict[str, str]):
    return SimpleNamespace(headers=headers, cookies=cookies, query_params={})


def denied(fn) -> int:
    try:
        fn()
    except HTTPException as exc:
        return exc.status_code
    raise AssertionError("expected HTTPException")


def main() -> None:
    m = load_agentd()

    # Token gate: with no TOKEN configured (default), reads are allowed.
    m.require_token(request({}, {}))

    # CSRF gate: missing cookie/header -> 403; full match -> ok.
    assert denied(lambda: m.require_csrf(request({}, {}))) == 403
    m.require_csrf(
        request({"x-csrf-token": m.CSRF_TOKEN}, {m.CSRF_COOKIE: m.CSRF_TOKEN})
    )

    # Action routing: an unknown action is rejected (never silently shelled).
    assert denied(lambda: m.run_action("definitely-not-an-action", {})) == 400

    # Read model shapes (imported library, not scraped text).
    assert isinstance(m.mcp_servers(), list)
    snap = m.ac.query_snapshot()
    for key in ("pending_approvals", "ledger_ok", "profiles"):
        assert key in snap, f"snapshot missing {key}"
    assert isinstance(m.ac.query_profiles(), list)

    print("agentd smoke OK")


if __name__ == "__main__":
    main()
