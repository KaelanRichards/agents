# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2"]
# ///
"""bigquery-mcp — local read-only BigQuery MCP facade using gcloud/bq auth."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("bigquery_mcp")

DEFAULT_PROJECT = os.environ.get("BIGQUERY_MCP_PROJECT", "vizcom-web").strip() or "vizcom-web"
DEFAULT_LOCATION = os.environ.get("BIGQUERY_MCP_LOCATION", "US").strip() or "US"
DEFAULT_MAX_BYTES = int(os.environ.get("BIGQUERY_MCP_MAX_BYTES_BILLED", "1000000000"))
MAX_SQL_CHARS = 50_000

MUTATING_SQL = re.compile(
    r"\b("
    r"alter|assert|call|clone|create|delete|drop|execute\s+immediate|export|grant|import|insert|load|merge|"
    r"replace|revoke|set|truncate|update"
    r")\b",
    re.IGNORECASE,
)


class BigQueryMcpError(ValueError):
    """Expected user/configuration error."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _dry_run() -> bool:
    return _truthy(os.environ.get("BIGQUERY_MCP_DRY_RUN"))


def _require(name: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise BigQueryMcpError(f"{name} is required")
    return value


def _project(project_id: str = "") -> str:
    return _require("project_id", project_id or DEFAULT_PROJECT)


def _location(location: str = "") -> str:
    return _require("location", location or DEFAULT_LOCATION)


def _identifier(name: str, value: str) -> str:
    value = _require(name, value)
    if not re.fullmatch(r"[A-Za-z0-9_:-]+", value):
        raise BigQueryMcpError(f"{name} must contain only letters, numbers, underscores, hyphens, or colons")
    return value


def _sql(value: str) -> str:
    sql = _require("sql", value)
    if len(sql) > MAX_SQL_CHARS:
        raise BigQueryMcpError("sql is too long")
    stripped = _strip_sql_comments(sql).strip()
    if ";" in stripped.rstrip(";"):
        raise BigQueryMcpError("multiple SQL statements are not allowed")
    stripped = stripped.rstrip(";").strip()
    if not re.match(r"(?is)^(select|with|explain)\b", stripped):
        raise BigQueryMcpError("only read-only SELECT, WITH, or EXPLAIN queries are allowed")
    if MUTATING_SQL.search(stripped):
        raise BigQueryMcpError("write-capable SQL keywords are not allowed in the read-only BigQuery MCP facade")
    return stripped


def _strip_sql_comments(sql: str) -> str:
    lines: list[str] = []
    in_block = False
    for raw_line in sql.splitlines():
        line = raw_line
        if in_block:
            if "*/" in line:
                line = line.split("*/", 1)[1]
                in_block = False
            else:
                continue
        while "/*" in line:
            before, after = line.split("/*", 1)
            if "*/" in after:
                line = before + after.split("*/", 1)[1]
            else:
                line = before
                in_block = True
                break
        lines.append(line.split("--", 1)[0])
    return "\n".join(lines)


def _json_response(status: str, result: dict[str, Any]) -> str:
    return json.dumps({"status": status, "result": result}, indent=2, sort_keys=True)


def _bq(args: list[str], timeout: int = 120) -> dict[str, Any]:
    if not shutil.which("bq"):
        raise BigQueryMcpError("bq CLI is not installed; install gcloud-cli and authenticate with gcloud auth login")
    if _dry_run():
        return {"dry_run": True, "command": ["bq", *args]}
    proc = subprocess.run(["bq", *args], capture_output=True, text=True, timeout=timeout)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise BigQueryMcpError(stderr or stdout or f"bq exited with status {proc.returncode}")
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"output": stdout}


def _run(action: str, result_fn) -> str:
    try:
        return _json_response("ok", result_fn())
    except BigQueryMcpError as exc:
        return _json_response("error", {"error": str(exc), "action": action})
    except Exception as exc:  # noqa: BLE001
        return _json_response("error", {"error": f"unexpected error: {exc}", "action": action})


@mcp.tool()
def bigquery_list_datasets(project_id: str = "") -> str:
    """List BigQuery datasets in a project using current gcloud/bq auth."""

    def run() -> dict[str, Any]:
        project = _project(project_id)
        return {"project_id": project, "datasets": _bq(["ls", "--format=prettyjson", f"--project_id={project}"])}

    return _run("bigquery_list_datasets", run)


@mcp.tool()
def bigquery_list_tables(dataset_id: str, project_id: str = "") -> str:
    """List tables in one BigQuery dataset using current gcloud/bq auth."""

    def run() -> dict[str, Any]:
        project = _project(project_id)
        dataset = _identifier("dataset_id", dataset_id)
        return {"project_id": project, "dataset_id": dataset, "tables": _bq(["ls", "--format=prettyjson", f"{project}:{dataset}"])}

    return _run("bigquery_list_tables", run)


@mcp.tool()
def bigquery_show_table_schema(dataset_id: str, table_id: str, project_id: str = "") -> str:
    """Show a BigQuery table schema using current gcloud/bq auth."""

    def run() -> dict[str, Any]:
        project = _project(project_id)
        dataset = _identifier("dataset_id", dataset_id)
        table = _identifier("table_id", table_id)
        table_ref = f"{project}:{dataset}.{table}"
        return {"project_id": project, "dataset_id": dataset, "table_id": table, "schema": _bq(["show", "--schema", "--format=prettyjson", table_ref])}

    return _run("bigquery_show_table_schema", run)


@mcp.tool()
def bigquery_estimate_query(sql: str, project_id: str = "", location: str = "") -> str:
    """Dry-run a read-only BigQuery SQL query to estimate bytes before execution."""

    def run() -> dict[str, Any]:
        project = _project(project_id)
        loc = _location(location)
        query = _sql(sql)
        return {
            "project_id": project,
            "location": loc,
            "dry_run": _bq(
                [
                    "query",
                    "--dry_run",
                    "--use_legacy_sql=false",
                    "--format=prettyjson",
                    f"--project_id={project}",
                    f"--location={loc}",
                    query,
                ],
                timeout=60,
            ),
        }

    return _run("bigquery_estimate_query", run)


@mcp.tool()
def bigquery_execute_sql_readonly(
    sql: str,
    project_id: str = "",
    location: str = "",
    maximum_bytes_billed: int = DEFAULT_MAX_BYTES,
) -> str:
    """Execute one read-only BigQuery SELECT/WITH/EXPLAIN query with a bytes-billed cap."""

    def run() -> dict[str, Any]:
        project = _project(project_id)
        loc = _location(location)
        query = _sql(sql)
        if maximum_bytes_billed < 1 or maximum_bytes_billed > DEFAULT_MAX_BYTES:
            raise BigQueryMcpError(f"maximum_bytes_billed must be between 1 and {DEFAULT_MAX_BYTES}")
        return {
            "project_id": project,
            "location": loc,
            "maximum_bytes_billed": maximum_bytes_billed,
            "rows": _bq(
                [
                    "query",
                    "--use_legacy_sql=false",
                    "--format=prettyjson",
                    f"--project_id={project}",
                    f"--location={loc}",
                    f"--maximum_bytes_billed={maximum_bytes_billed}",
                    query,
                ],
                timeout=180,
            ),
        }

    return _run("bigquery_execute_sql_readonly", run)


if __name__ == "__main__":
    mcp.run()
