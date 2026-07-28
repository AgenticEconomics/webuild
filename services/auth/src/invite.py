"""Seed invite-whitelist users into the database on startup.

Invite-only mode: there is no public registration. Accounts are provisioned
from a JSON whitelist file and handed out manually by email.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import bcrypt
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from webuild_shared.models import User

log = structlog.get_logger()

DEFAULT_WHITELIST_PATHS = (
    "/run/secrets/invite_whitelist",
    "/run/secrets/invite_whitelist.json",
    "/app/invite_whitelist.json",
    "invite_whitelist.json",
)


def _resolve_whitelist_path() -> Path | None:
    env_path = os.environ.get("INVITE_WHITELIST_PATH", "").strip()
    candidates = [env_path] if env_path else []
    candidates.extend(DEFAULT_WHITELIST_PATHS)
    for p in candidates:
        if not p:
            continue
        path = Path(p)
        if path.is_file():
            return path
    return None


async def seed_invite_whitelist(session_factory: async_sessionmaker[AsyncSession]) -> dict:
    """Upsert whitelist users. Returns summary stats."""
    path = _resolve_whitelist_path()
    if path is None:
        log.warning("invite.whitelist_missing", detail="No invite_whitelist.json found — skip seed")
        return {"seeded": 0, "skipped": 0, "path": None}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("invite.whitelist_invalid", path=str(path), error=str(exc))
        return {"seeded": 0, "skipped": 0, "path": str(path), "error": str(exc)}

    users = data.get("users") or []
    if not isinstance(users, list):
        log.error("invite.whitelist_bad_shape", path=str(path))
        return {"seeded": 0, "skipped": 0, "path": str(path)}

    seeded = 0
    skipped = 0
    async with session_factory() as session:
        for entry in users:
            username = (entry.get("username") or "").strip()
            email = (entry.get("email") or "").strip()
            password = entry.get("password") or ""
            role = (entry.get("role") or "developer").strip() or "developer"
            if not username or not email or not password:
                skipped += 1
                continue

            existing = await session.execute(select(User).where(User.username == username))
            user = existing.scalar_one_or_none()
            if user is not None:
                # Keep existing account; do not reset password on every restart
                skipped += 1
                continue

            # Also skip if email already taken by another user
            email_hit = await session.execute(select(User).where(User.email == email))
            if email_hit.scalar_one_or_none() is not None:
                log.warning("invite.email_taken", username=username, email=email)
                skipped += 1
                continue

            password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            session.add(
                User(
                    username=username,
                    email=email,
                    password_hash=password_hash,
                    role=role,
                )
            )
            seeded += 1
            log.info("invite.user_seeded", username=username, role=role)

        await session.commit()

    log.info(
        "invite.seed_complete",
        path=str(path),
        seeded=seeded,
        skipped=skipped,
        total=len(users),
        invite_email=data.get("invite_email"),
    )
    return {
        "seeded": seeded,
        "skipped": skipped,
        "total": len(users),
        "path": str(path),
        "invite_email": data.get("invite_email", "jerry.zhang@datoms.cn"),
    }


def get_invite_email() -> str:
    """Public invite contact — safe to expose to the UI."""
    env = os.environ.get("INVITE_EMAIL", "").strip()
    if env:
        return env
    path = _resolve_whitelist_path()
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            email = (data.get("invite_email") or "").strip()
            if email:
                return email
        except Exception:
            pass
    return "jerry.zhang@datoms.cn"
