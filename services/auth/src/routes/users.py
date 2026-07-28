"""User management routes: CRUD with admin/self authorization."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import bcrypt
from webuild_shared.auth_middleware import get_current_user
from webuild_shared.db import get_async_session
from webuild_shared.models import User

from src.middleware.rbac import require_role

log = structlog.get_logger()

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: str = "developer"


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    role: str | None = None
    password: str | None = None


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str

    model_config = {"from_attributes": True}


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    current_user: dict = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new user (admin only).

    Public self-registration is disabled — WeBuild is invite-only.
    Invite accounts are seeded from the whitelist; additional users
    must be created by an administrator.
    """
    # Check for existing username
    existing = await session.execute(
        select(User).where(User.username == body.username)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )

    # Check for existing email
    existing_email = await session.execute(
        select(User).where(User.email == body.email)
    )
    if existing_email.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists",
        )

    password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()

    user = User(
        username=body.username,
        email=body.email,
        password_hash=password_hash,
        role=body.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    log.info("users.created", user_id=str(user.id), by=current_user["user_id"])
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
    )


@router.get("", response_model=list[UserResponse])
async def list_users(
    current_user: dict = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_async_session),
    skip: int = 0,
    limit: int = 50,
):
    """List all users (admin only)."""
    result = await session.execute(
        select(User).offset(skip).limit(limit).order_by(User.created_at)
    )
    users = result.scalars().all()
    return [
        UserResponse(
            id=str(u.id),
            username=u.username,
            email=u.email,
            role=u.role,
        )
        for u in users
    ]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Get a user by ID (admin or self)."""
    is_admin = "admin" in current_user.get("scopes", [])
    is_self = current_user["user_id"] == str(user_id)

    if not is_admin and not is_self:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Update a user (admin or self)."""
    is_admin = "admin" in current_user.get("scopes", [])
    is_self = current_user["user_id"] == str(user_id)

    if not is_admin and not is_self:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if body.email is not None:
        user.email = body.email
    if body.role is not None and is_admin:
        # Only admins can change roles
        user.role = body.role
    if body.password is not None:
        user.password_hash = bcrypt.hashpw(
            body.password.encode(), bcrypt.gensalt()
        ).decode()

    await session.commit()
    await session.refresh(user)

    log.info("users.updated", user_id=str(user.id), by=current_user["user_id"])
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
    )
