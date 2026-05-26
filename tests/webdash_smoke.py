# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi>=0.110", "uvicorn>=0.30"]
# ///
"""Smoke checks for web dashboard mutation auth helpers."""

from __future__ import annotations

import importlib.util
import pathlib
from types import SimpleNamespace

from fastapi import HTTPException


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_dashboard():
    path = ROOT / "web" / "dashboard.py"
    spec = importlib.util.spec_from_file_location("webdash", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def request(headers: dict[str, str], cookies: dict[str, str], scheme: str = "http"):
    return SimpleNamespace(headers=headers, cookies=cookies, url=SimpleNamespace(scheme=scheme))


def denied(fn) -> int:
    try:
        fn()
    except HTTPException as exc:
        return exc.status_code
    raise AssertionError("expected HTTPException")


def main() -> None:
    dash = load_dashboard()
    old_token = dash.TOKEN
    try:
        dash.TOKEN = ""
        assert denied(lambda: dash._require_run_auth(request({"host": "localhost:8787"}, {}))) == 403

        dash.TOKEN = "secret"
        assert denied(
            lambda: dash._require_run_auth(
                request(
                    {
                        "host": "localhost:8787",
                        "origin": "https://evil.example",
                        "x-csrf-token": dash.CSRF_TOKEN,
                    },
                    {dash.CSRF_COOKIE: dash.CSRF_TOKEN},
                )
            )
        ) == 403
        assert denied(
            lambda: dash._require_run_auth(
                request({"host": "localhost:8787"}, {dash.CSRF_COOKIE: dash.CSRF_TOKEN})
            )
        ) == 403

        dash._require_run_auth(
            request(
                {
                    "host": "localhost:8787",
                    "origin": "http://localhost:8787",
                    "x-csrf-token": dash.CSRF_TOKEN,
                },
                {dash.CSRF_COOKIE: dash.CSRF_TOKEN},
            )
        )
    finally:
        dash.TOKEN = old_token
    print("webdash smoke OK")


if __name__ == "__main__":
    main()
