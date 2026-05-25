"""Create stable Windmill resource aliases used by personal-actions."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS_DIR = Path.home() / ".config" / "agents-secrets"
ADMIN_ENV = SECRETS_DIR / "windmill-admin.env"

ALIASES = {
    "slack": "u/admin/slack",
    "gmail": "u/admin/gmail",
    "gcal": "u/admin/gcal",
    "gmail_compose": "u/admin/gmail_compose",
}


class ApiError(RuntimeError):
    pass


def load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def request(method: str, base_url: str, path: str, token: str | None = None, body: object | None = None) -> str:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(f"{base_url}{path}", data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"{method} {path} failed: HTTP {exc.code}: {text}") from exc


def main() -> int:
    admin = load_env(ADMIN_ENV)
    base_url = admin.get("WINDMILL_BASE_URL", os.environ.get("WINDMILL_BASE_URL", "http://localhost:8790")).rstrip("/")
    workspace = admin.get("WINDMILL_WORKSPACE", os.environ.get("WINDMILL_WORKSPACE", "personal"))
    email = admin.get("WINDMILL_ADMIN_EMAIL", os.environ.get("WINDMILL_ADMIN_EMAIL", "admin@windmill.dev"))
    password = admin.get("WINDMILL_ADMIN_PASSWORD", os.environ.get("WINDMILL_ADMIN_PASSWORD", ""))
    if not password:
        raise ApiError(f"missing WINDMILL_ADMIN_PASSWORD in {ADMIN_ENV}")
    token = request("POST", base_url, "/api/auth/login", body={"email": email, "password": password}).strip()
    resources = json.loads(request("GET", base_url, f"/api/w/{workspace}/resources/list", token=token))
    by_type = {
        resource["resource_type"]: resource["path"]
        for resource in resources
        if resource.get("resource_type") in ALIASES and resource.get("path") not in set(ALIASES.values())
    }
    for resource in resources:
        if resource.get("path") in set(ALIASES.values()):
            by_type.setdefault(resource["resource_type"], resource["path"])
    linked = 0
    for resource_type, dest in ALIASES.items():
        src = by_type.get(resource_type)
        if not src:
            print(f"missing {resource_type}: connect a {resource_type} resource first")
            continue
        encoded = urllib.parse.quote(src, safe="")
        value = json.loads(request("GET", base_url, f"/api/w/{workspace}/resources/get_value/{encoded}", token=token))
        request(
            "POST",
            base_url,
            f"/api/w/{workspace}/resources/create?update_if_exists=true",
            token=token,
            body={
                "path": dest,
                "value": value,
                "resource_type": resource_type,
                "description": f"Stable alias for {src}",
            },
        )
        linked += 1
        print(f"linked {resource_type}: {src} -> {dest}")
    return 0 if linked else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(f"windmill-link-personal-resources: {exc}", file=sys.stderr)
        raise SystemExit(1)
