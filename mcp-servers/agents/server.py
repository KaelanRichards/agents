# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2"]
# ///
"""agents — an MCP server exposing this environment's own tooling to Claude + Codex.

Tools: repo status/log/diff (jj or git), project task discovery + run, MCP-server list,
and config sync. Operates on the launching client's working directory by default.
"""

import json
import os
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agents")


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 60) -> str:
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        out = (r.stdout or "") + (r.stderr or "")
        return out.strip() or "(no output)"
    except FileNotFoundError:
        return f"error: '{cmd[0]}' not found on PATH"
    except subprocess.TimeoutExpired:
        return f"error: '{' '.join(cmd)}' timed out after {timeout}s"
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def _is_jj(path: str) -> bool:
    return subprocess.run(["jj", "root"], cwd=path, capture_output=True).returncode == 0


def _cwd(path: str) -> str:
    return path or os.getcwd()


def _mutation_allowed() -> bool:
    return os.environ.get("AGENTS_MCP_ALLOW_MUTATION") == "1"


@mcp.tool()
def repo_status(path: str = "") -> str:
    """Working-copy status of the repo (jj st, or git status)."""
    p = _cwd(path)
    return _run(["jj", "st"] if _is_jj(p) else ["git", "status", "-sb"], cwd=p)


@mcp.tool()
def repo_log(limit: int = 10, path: str = "") -> str:
    """Recent commits (jj log / git log)."""
    p = _cwd(path)
    if _is_jj(p):
        return _run(["jj", "log", "-n", str(limit), "--no-graph"], cwd=p)
    return _run(["git", "log", "--oneline", "-n", str(limit)], cwd=p)


@mcp.tool()
def repo_diff(path: str = "") -> str:
    """Current uncommitted diff (jj diff / git diff)."""
    p = _cwd(path)
    return _run(["jj", "diff"] if _is_jj(p) else ["git", "diff"], cwd=p)


@mcp.tool()
def list_tasks(path: str = "") -> str:
    """List runnable project tasks: justfile recipes and package.json scripts."""
    p = Path(_cwd(path))
    out: list[str] = []
    if (p / "justfile").exists() or (p / "Justfile").exists():
        out.append("just recipes:\n" + _run(["just", "--summary"], cwd=str(p)))
    pj = p / "package.json"
    if pj.exists():
        try:
            scripts = json.loads(pj.read_text()).get("scripts", {})
            if scripts:
                out.append(
                    "package.json scripts:\n"
                    + "\n".join(f"  {k}: {v}" for k, v in scripts.items())
                )
        except (json.JSONDecodeError, OSError):
            pass
    return "\n\n".join(out) or "(no justfile recipes or package.json scripts found)"


@mcp.tool()
def run_task(name: str, path: str = "") -> str:
    """Run a project task by name — must be a known justfile recipe or package.json script."""
    if not _mutation_allowed():
        return "error: mutating tools disabled; set AGENTS_MCP_ALLOW_MUTATION=1 to run tasks"
    p = Path(_cwd(path))
    if (p / "justfile").exists() or (p / "Justfile").exists():
        if name in _run(["just", "--summary"], cwd=str(p)).split():
            return _run(["just", name], cwd=str(p), timeout=600)
    pj = p / "package.json"
    if pj.exists():
        try:
            scripts = json.loads(pj.read_text()).get("scripts", {})
            if name in scripts:
                runner = "pnpm" if (p / "pnpm-lock.yaml").exists() else "npm"
                return _run([runner, "run", name], cwd=str(p), timeout=600)
        except (json.JSONDecodeError, OSError):
            pass
    return f"error: task '{name}' not found — call list_tasks first"


@mcp.tool()
def list_mcp_servers() -> str:
    """List the MCP servers in the shared canonical config (~/.config/agents/mcp.json)."""
    f = Path.home() / ".config/agents/mcp.json"
    if not f.exists():
        return "(no mcp.json)"
    servers = json.loads(f.read_text()).get("mcpServers", {})
    if not servers:
        return "(none configured)"
    return "\n".join(
        f"{k}: {v.get('type', 'stdio')}  {v.get('command') or v.get('url', '')}"
        for k, v in servers.items()
    )


@mcp.tool()
def sync_config() -> str:
    """Regenerate Claude + Codex config from the canonical source (mcp-sync && agents-sync)."""
    if not _mutation_allowed():
        return "error: mutating tools disabled; set AGENTS_MCP_ALLOW_MUTATION=1 to sync config"
    return _run(["mcp-sync"]) + "\n" + _run(["agents-sync"])


if __name__ == "__main__":
    mcp.run()
