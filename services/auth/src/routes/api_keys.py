"""API key management routes: create, list, delete."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from webuild_shared.auth_middleware import get_current_user
from webuild_shared.db import get_async_session
from webuild_shared.models import ApiKey

log = structlog.get_logger()

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class ApiKeyCreate(BaseModel):
    name: str | None = None
    scopes: list[str] = ["agent.use"]
    expires_at: datetime | None = None


class ApiKeyCreatedResponse(BaseModel):
    id: str
    name: str | None
    key: str  # Returned only once at creation time
    scopes: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyListResponse(BaseModel):
    id: str
    name: str | None
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Helpers ──────────────────────────────────────────────────────────────────


def generate_api_key() -> tuple[str, str]:
    """Generate an API key and return (plaintext_key, sha256_hash).

    Key format: 'wb-' prefix + base64-encoded 32 random bytes.
    Only the SHA-256 hash is stored in the database.
    """
    raw = secrets.token_bytes(32)
    b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    plaintext = f"wb-{b64}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    return plaintext, key_hash


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    body: ApiKeyCreate,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new API key. The plaintext key is returned only once."""
    plaintext, key_hash = generate_api_key()

    api_key = ApiKey(
        user_id=uuid.UUID(current_user["user_id"]),
        key_hash=key_hash,
        key_prefix=plaintext[:7],  # "wb-XXXX" prefix for identification
        name=body.name,
        scopes=body.scopes,
        expires_at=body.expires_at,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)

    log.info(
        "api_keys.created",
        key_id=str(api_key.id),
        user_id=current_user["user_id"],
    )
    return ApiKeyCreatedResponse(
        id=str(api_key.id),
        name=api_key.name,
        key=plaintext,
        scopes=api_key.scopes if isinstance(api_key.scopes, list) else [],
        created_at=api_key.created_at,
    )


@router.get("", response_model=list[ApiKeyListResponse])
async def list_api_keys(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List all API keys belonging to the current user."""
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.user_id == uuid.UUID(current_user["user_id"]))
        .order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        ApiKeyListResponse(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=k.scopes if isinstance(k.scopes, list) else [],
            expires_at=k.expires_at,
            created_at=k.created_at,
        )
        for k in keys
    ]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete an API key (owner or admin)."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    is_admin = "admin" in current_user.get("scopes", [])
    is_owner = api_key.user_id == uuid.UUID(current_user["user_id"])

    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    await session.delete(api_key)
    await session.commit()

    log.info(
        "api_keys.deleted",
        key_id=str(key_id),
        by=current_user["user_id"],
    )
