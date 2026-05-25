# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2"]
# ///
"""Smoke test for the local read-only BigQuery MCP facade."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp-servers" / "bigquery" / "server.py"


def load_server():
    spec = importlib.util.spec_from_file_location("bigquery_mcp_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    old_env = os.environ.copy()
    try:
        os.environ["BIGQUERY_MCP_DRY_RUN"] = "1"
        mod = load_server()

        datasets = json.loads(mod.bigquery_list_datasets())
        assert datasets["status"] == "ok"
        assert datasets["result"]["project_id"] == "vizcom-web"
        assert datasets["result"]["datasets"]["command"][0:3] == ["bq", "ls", "--format=prettyjson"]

        estimate = json.loads(mod.bigquery_estimate_query("SELECT 1 AS ok"))
        assert estimate["status"] == "ok"
        assert "--dry_run" in estimate["result"]["dry_run"]["command"]

        query = json.loads(mod.bigquery_execute_sql_readonly("WITH x AS (SELECT 1 AS ok) SELECT ok FROM x"))
        assert query["status"] == "ok"
        assert "--maximum_bytes_billed=1000000000" in query["result"]["rows"]["command"]

        rejected = json.loads(mod.bigquery_execute_sql_readonly("DELETE FROM dataset.table WHERE TRUE"))
        assert rejected["status"] == "error"
        assert "read-only" in rejected["result"]["error"] or "write-capable" in rejected["result"]["error"]

        multi = json.loads(mod.bigquery_execute_sql_readonly("SELECT 1; SELECT 2"))
        assert multi["status"] == "error"
        assert "multiple SQL statements" in multi["result"]["error"]

        print("bigquery MCP smoke OK")
    finally:
        os.environ.clear()
        os.environ.update(old_env)


if __name__ == "__main__":
    main()
