"""Create stable Windmill resource aliases used by personal-actions."""

from __future__ import annotations

import json
import os
import sys
import argparse
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS_DIR = Path.home() / ".config" / "agents-secrets"
ADMIN_ENV = SECRETS_DIR / "windmill-admin.env"

STABLE_ALIASES = {
    "slack": ("slack", "u/admin/slack"),
    "gmail": ("gmail", "u/admin/gmail"),
    "gcal": ("gcal", "u/admin/gcal"),
    "work_gmail": ("gmail", "u/admin/work_gmail"),
    "work_gcal": ("gcal", "u/admin/work_gcal"),
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


def source_for(
    resources: list[dict[str, str]],
    resource_type: str,
    dest: str,
    explicit: str,
    work: bool,
) -> str:
    if explicit:
        return explicit
    stable_paths = {alias for _, alias in STABLE_ALIASES.values()}
    candidates = [
        resource["path"]
        for resource in resources
        if resource.get("resource_type") == resource_type and resource.get("path") not in stable_paths
    ]
    if not candidates:
        existing = [resource["path"] for resource in resources if resource.get("path") == dest]
        return existing[0] if existing else ""
    if work:
        existing = [resource["path"] for resource in resources if resource.get("path") == dest]
        if existing:
            return existing[0]
        return candidates[-1] if len(candidates) > 1 else ""
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--personal-gmail-source", default="")
    parser.add_argument("--personal-gcal-source", default="")
    parser.add_argument("--work-gmail-source", default="")
    parser.add_argument("--work-gcal-source", default="")
    parser.add_argument("--include-work", action="store_true", help="also create u/admin/work_gmail and u/admin/work_gcal")
    args = parser.parse_args()
    admin = load_env(ADMIN_ENV)
    base_url = admin.get("WINDMILL_BASE_URL", os.environ.get("WINDMILL_BASE_URL", "http://localhost:8790")).rstrip("/")
    workspace = admin.get("WINDMILL_WORKSPACE", os.environ.get("WINDMILL_WORKSPACE", "personal"))
    email = admin.get("WINDMILL_ADMIN_EMAIL", os.environ.get("WINDMILL_ADMIN_EMAIL", "admin@windmill.dev"))
    password = admin.get("WINDMILL_ADMIN_PASSWORD", os.environ.get("WINDMILL_ADMIN_PASSWORD", ""))
    if not password:
        raise ApiError(f"missing WINDMILL_ADMIN_PASSWORD in {ADMIN_ENV}")
    token = request("POST", base_url, "/api/auth/login", body={"email": email, "password": password}).strip()
    resources = json.loads(request("GET", base_url, f"/api/w/{workspace}/resources/list", token=token))
    explicit = {
        "gmail": args.personal_gmail_source,
        "gcal": args.personal_gcal_source,
        "work_gmail": args.work_gmail_source,
        "work_gcal": args.work_gcal_source,
    }
    linked = 0
    aliases = dict(STABLE_ALIASES)
    if not args.include_work:
        aliases.pop("work_gmail")
        aliases.pop("work_gcal")
    for name, (resource_type, dest) in aliases.items():
        src = source_for(resources, resource_type, dest, explicit.get(name, ""), name.startswith("work_"))
        if not src:
            print(f"missing {name}: connect a {resource_type} resource first")
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
