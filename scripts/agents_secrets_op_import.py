#!/usr/bin/env python3
"""Import local agents env secrets into 1Password without printing values."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


SECRETS_DIR = Path.home() / ".config" / "agents-secrets"
REF_ENV = SECRETS_DIR / "agents.1password.env"

ITEMS: dict[str, list[tuple[Path, str, str]]] = {
    "personal-actions": [
        (SECRETS_DIR / "personal-actions.env", "PERSONAL_ACTIONS_PROVIDER", "provider"),
        (SECRETS_DIR / "personal-actions.env", "PERSONAL_ACTIONS_WEBHOOK_URL", "webhook_url"),
        (SECRETS_DIR / "personal-actions.env", "PERSONAL_ACTIONS_WEBHOOK_TOKEN", "webhook_token"),
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_ACTIONS_WEBHOOK_HMAC_SECRET",
            "webhook_hmac_secret",
        ),
        (SECRETS_DIR / "personal-actions.env", "PERSONAL_ACTIONS_DRY_RUN", "dry_run"),
        (SECRETS_DIR / "personal-actions.env", "PERSONAL_ACTIONS_ALLOW_HTTP", "allow_http"),
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_ACTIONS_REQUIRE_APPROVAL",
            "require_approval",
        ),
    ],
    "gmail-compose": [
        (SECRETS_DIR / "personal-actions.env", "PERSONAL_GMAIL_COMPOSE_CLIENT_ID", "client_id"),
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_GMAIL_COMPOSE_CLIENT_SECRET",
            "client_secret",
        ),
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_GMAIL_COMPOSE_REFRESH_TOKEN",
            "refresh_token",
        ),
    ],
    "gmail-modify": [
        (SECRETS_DIR / "personal-actions.env", "PERSONAL_GMAIL_MODIFY_CLIENT_ID", "client_id"),
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_GMAIL_MODIFY_CLIENT_SECRET",
            "client_secret",
        ),
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_GMAIL_MODIFY_REFRESH_TOKEN",
            "refresh_token",
        ),
    ],
    "work-gmail-compose": [
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_WORK_GMAIL_COMPOSE_CLIENT_ID",
            "client_id",
        ),
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_WORK_GMAIL_COMPOSE_CLIENT_SECRET",
            "client_secret",
        ),
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_WORK_GMAIL_COMPOSE_REFRESH_TOKEN",
            "refresh_token",
        ),
    ],
    "work-gmail-modify": [
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_WORK_GMAIL_MODIFY_CLIENT_ID",
            "client_id",
        ),
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_WORK_GMAIL_MODIFY_CLIENT_SECRET",
            "client_secret",
        ),
        (
            SECRETS_DIR / "personal-actions.env",
            "PERSONAL_WORK_GMAIL_MODIFY_REFRESH_TOKEN",
            "refresh_token",
        ),
    ],
    "windmill-admin": [
        (SECRETS_DIR / "windmill-admin.env", "WINDMILL_BASE_URL", "base_url"),
        (SECRETS_DIR / "windmill-admin.env", "WINDMILL_ADMIN_EMAIL", "admin_email"),
        (SECRETS_DIR / "windmill-admin.env", "WINDMILL_ADMIN_PASSWORD", "admin_password"),
        (SECRETS_DIR / "windmill-admin.env", "WINDMILL_WORKSPACE", "workspace"),
    ],
    "windmill-oauth": [
        (SECRETS_DIR / "windmill-oauth.env", "GOOGLE_OAUTH_CLIENT_ID", "google_client_id"),
        (
            SECRETS_DIR / "windmill-oauth.env",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "google_client_secret",
        ),
        (
            SECRETS_DIR / "windmill-oauth.env",
            "WINDMILL_GMAIL_OAUTH_CLIENT_ID",
            "gmail_client_id",
        ),
        (
            SECRETS_DIR / "windmill-oauth.env",
            "WINDMILL_GMAIL_OAUTH_CLIENT_SECRET",
            "gmail_client_secret",
        ),
        (SECRETS_DIR / "windmill-oauth.env", "WINDMILL_GCAL_OAUTH_CLIENT_ID", "gcal_client_id"),
        (
            SECRETS_DIR / "windmill-oauth.env",
            "WINDMILL_GCAL_OAUTH_CLIENT_SECRET",
            "gcal_client_secret",
        ),
        (
            SECRETS_DIR / "windmill-oauth.env",
            "WINDMILL_SLACK_OAUTH_CLIENT_ID",
            "slack_client_id",
        ),
        (
            SECRETS_DIR / "windmill-oauth.env",
            "WINDMILL_SLACK_OAUTH_CLIENT_SECRET",
            "slack_client_secret",
        ),
    ],
    "windmill-stack": [
        (SECRETS_DIR / "windmill.env", "POSTGRES_PASSWORD", "postgres_password"),
    ],
    "webdash": [
        (Path.home() / ".config" / "agents" / "webdash.env", "WEBDASH_TOKEN", "token"),
    ],
}


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def existing_item_titles(vault: str) -> set[str]:
    try:
        result = subprocess.run(
            ["op", "item", "list", "--vault", vault, "--format", "json"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(
            f"could not list items in 1Password vault {vault!r}. "
            "Run `op vault list` and pass the exact vault name with --vault. "
            f"op said: {detail}"
        ) from exc
    return {item["title"] for item in json.loads(result.stdout)}


def template(title: str, fields: dict[str, str]) -> dict[str, object]:
    return {
        "title": title,
        "category": "SECURE_NOTE",
        "fields": [
            {
                "id": name,
                "label": name,
                "type": "CONCEALED" if secretish(name) else "STRING",
                "value": value,
            }
            for name, value in fields.items()
        ],
    }


def secretish(name: str) -> bool:
    return any(part in name for part in ("secret", "token", "password"))


def create_item(vault: str, title: str, fields: dict[str, str]) -> None:
    payload = json.dumps(template(title, fields), separators=(",", ":"))
    subprocess.run(
        ["op", "item", "create", "--vault", vault, "-"],
        input=payload,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def write_ref_env(vault: str, plan: dict[str, dict[str, str]]) -> None:
    env_lines = [
        "# Generated by agents-secrets-op-import --write-env. Do not put raw secrets here.",
        "# Values are 1Password references resolved by op run.",
        "",
    ]
    for title, mappings in ITEMS.items():
        fields = plan.get(title, {})
        if not fields:
            continue
        env_lines.append(f"# {title}")
        for _path, env_key, field_name in mappings:
            if field_name in fields:
                env_lines.append(f"{env_key}=op://{vault}/{title}/{field_name}")
        env_lines.append("")

    SECRETS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    REF_ENV.write_text("\n".join(env_lines).rstrip() + "\n", encoding="utf-8")
    REF_ENV.chmod(0o600)
    print(f"wrote reference env: {REF_ENV}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default="Kaelan-Agents")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--write-env", action="store_true")
    args = parser.parse_args()

    env_cache: dict[Path, dict[str, str]] = {}
    plan: dict[str, dict[str, str]] = {}
    missing: list[str] = []

    for title, mappings in ITEMS.items():
        fields: dict[str, str] = {}
        for path, env_key, field_name in mappings:
            env = env_cache.setdefault(path, load_env(path))
            value = env.get(env_key) or os.environ.get(env_key, "")
            if value:
                fields[field_name] = value
        if fields:
            plan[title] = fields
        elif any(path.exists() for path, _, _ in mappings):
            missing.append(title)

    if not plan:
        print("No importable values found in ~/.config/agents-secrets.")
        return 1

    print(f"Vault: {args.vault}")
    print("Planned items:")
    for title, fields in plan.items():
        print(f"  {title}: {', '.join(sorted(fields))}")
    if missing:
        print("Items with source files but no mapped values:")
        for title in missing:
            print(f"  {title}")

    if not args.apply:
        if args.write_env:
            write_ref_env(args.vault, plan)
        print("Dry-run only. Re-run with --apply to create missing 1Password items.")
        return 0

    try:
        existing = existing_item_titles(args.vault)
    except RuntimeError as exc:
        print(f"agents-secrets-op-import: {exc}", file=sys.stderr)
        return 1
    for title, fields in plan.items():
        if title in existing:
            print(f"skip existing item: {title}")
            continue
        create_item(args.vault, title, fields)
        print(f"created item: {title}")
    if args.write_env:
        write_ref_env(args.vault, plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
