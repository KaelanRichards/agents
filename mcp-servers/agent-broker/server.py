# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2"]
# ///
"""agent-broker — profile-aware policy and audit MCP facade."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

AGENTS_HOME = Path.home() / ".config/agents"
CONTROL = AGENTS_HOME / "scripts" / "agent_control.py"
spec = importlib.util.spec_from_file_location("agent_control", CONTROL)
agent_control = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(agent_control)

mcp = FastMCP("agent-broker")


@mcp.tool()
def list_profiles() -> str:
    """List canonical agent permission profiles."""
    rows = []
    for path in agent_control.profile_files():
        data = agent_control.load_json(path)
        rows.append(
            {
                "name": data["name"],
                "risk": data["risk"],
                "description": data["description"],
            }
        )
    return json.dumps(rows, indent=2, sort_keys=True)


@mcp.tool()
def get_profile(name: str) -> str:
    """Return one canonical agent permission profile."""
    return json.dumps(agent_control.load_profile(name), indent=2, sort_keys=True)


@mcp.tool()
def authorize_tool_call(
    profile: str,
    server: str,
    tool: str,
    mutation: bool = False,
    context_tainted: bool = False,
) -> str:
    """Check whether a profile allows an MCP/tool call; records the decision in the run ledger.

    Set context_tainted=True when the call would act on data drawn from an untrusted source
    (a fetched web page, an inbound email/Slack message, a Datadog/Sentry payload). A mutation
    under taint always requires confirmation, and on high/critical profiles is refused outright."""
    decision = agent_control.broker_authorize(
        profile, server, tool, mutation, context_tainted
    )
    agent_control.append_ledger(
        {
            "kind": "broker",
            "status": "allowed" if decision["allowed"] else "denied",
            "profile": profile,
            "agent": "",
            "repo": "",
            "prompt": f"{server}.{tool}",
            "details": decision,
        }
    )
    return json.dumps(decision, indent=2, sort_keys=True)


@mcp.tool()
def list_pending_approvals(limit: int = 20) -> str:
    """List pending local approval inbox items."""
    conn = agent_control.approval_db()
    rows = conn.execute(
        "SELECT id, created_at, kind, summary, status FROM approvals WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return json.dumps([dict(row) for row in rows], indent=2, sort_keys=True)


if __name__ == "__main__":
    mcp.run()
