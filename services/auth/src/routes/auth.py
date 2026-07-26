"""Authentication routes: login, token refresh, current user."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import bcrypt
from webuild_shared.auth_middleware import get_current_user, get_jwt_manager
from webuild_shared.db import get_async_session
from webuild_shared.jwt import JWTManager
from webuild_shared.models import User

log = structlog.get_logger()

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    id: str
    username: str
    email: str
    role: str

    model_config = {"from_attributes": True}


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_user_by_username(
    username: str, session: AsyncSession
) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_async_session),
    jwt_manager: JWTManager = Depends(get_jwt_manager),
):
    """Authenticate with username + password and return access/refresh tokens."""
    user = await _get_user_by_username(body.username, session)
    if user is None:
        log.warning("auth.login.unknown_user", username=body.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        log.warning("auth.login.bad_password", username=body.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    access_token = jwt_manager.create_access_token(
        user_id=str(user.id),
        scopes=[user.role],
    )
    refresh_token = jwt_manager.create_refresh_token(user_id=str(user.id))

    log.info("auth.login.success", user_id=str(user.id))
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/token/refresh", response_model=AccessTokenResponse)
async def refresh_token(
    body: RefreshRequest,
    jwt_manager: JWTManager = Depends(get_jwt_manager),
):
    """Exchange a valid refresh token for a new access token."""
    try:
        payload = jwt_manager.verify_token(body.refresh_token, expected_type="refresh")
    except Exception as exc:
        log.warning("auth.refresh.invalid_token", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    new_access = jwt_manager.create_access_token(
        user_id=payload.sub,
        scopes=[],  # scopes are re-fetched from DB on next login
    )
    return AccessTokenResponse(access_token=new_access)


@router.get("/me", response_model=UserInfo)
async def me(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Return the currently authenticated user's info."""
    result = await session.execute(
        select(User).where(User.id == current_user["user_id"])
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return UserInfo(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
    )
