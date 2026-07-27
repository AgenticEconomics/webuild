"""WeBuild Relay Server — FastAPI application entry point.

Provides:
  - WebSocket endpoint at /ws for ACP relay
  - REST endpoints at /sessions for session management
  - Health check at /health
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from webuild_shared.db import get_engine, get_session_factory
from webuild_shared.jwt import JWTManager
from webuild_shared.logging import setup_logging
from webuild_shared.auth_middleware import get_current_user

from src.acp.router import AcpRouter
from src.persistence import SessionStore
from src.relay import init_relay, ws_router
from src.session_manager import SessionManager

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Globals initialized in lifespan
# ---------------------------------------------------------------------------
_session_manager: SessionManager | None = None
_router: AcpRouter | None = None
_store: SessionStore | None = None
_jwt: JWTManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    global _session_manager, _router, _store, _jwt

    setup_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        json_output=os.environ.get("LOG_JSON", "false").lower() == "true",
    )

    logger.info("relay.starting")

    # Initialize shared dependencies
    _jwt = JWTManager()

    # Initialize persistence (optional — relay works without DB)
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        try:
            engine = get_engine(db_url)
            # Import relay models to register their tables with Base
            from src.persistence import RelaySession, RelayMessage  # noqa: F401
            from webuild_shared.db import Base
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            factory = get_session_factory(engine)
            _store = SessionStore(factory)
            logger.info("relay.persistence.enabled")
        except Exception:
            logger.exception("relay.persistence.failed")
            _store = None
    else:
        logger.warning("relay.persistence.disabled", reason="DATABASE_URL not set")
        _store = None

    # Initialize session manager and router
    _session_manager = SessionManager()
    _router = AcpRouter(_session_manager, _store)

    # Wire up the relay WebSocket handler
    init_relay(_session_manager, _router, _store, _jwt)

    logger.info("relay.started")
    yield

    logger.info("relay.stopping")
    _session_manager = None
    _router = None
    _store = None
    _jwt = None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="WeBuild Relay Server",
    description="ACP bridge between Web IDE browsers and local WeBuild Agent instances",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount WebSocket routes
app.include_router(ws_router)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=64)


class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    status: str
    title: str | None = None
    model: str | None = None
    browser_connected: bool = False
    agent_connected: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class MessageResponse(BaseModel):
    id: int
    session_id: str
    seq: int
    direction: str
    method: str | None = None
    payload: dict[str, Any]
    created_at: str | None = None


class HealthResponse(BaseModel):
    status: str
    active_sessions: int
    total_sessions: int


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint."""
    assert _session_manager is not None
    return HealthResponse(
        status="healthy",
        active_sessions=await _session_manager.get_active_count(),
        total_sessions=await _session_manager.get_total_count(),
    )


@app.get("/discover", tags=["sessions"])
async def discover_sessions():
    """List sessions that have a browser connected but no agent.

    Internal endpoint used by the agent service to find sessions to join.
    No authentication required (internal network only).
    """
    assert _session_manager is not None
    result = []
    async with _session_manager._lock:
        for sid, pair in _session_manager._sessions.items():
            if pair.browser_ws is not None and pair.agent_ws is None:
                result.append({
                    "session_id": sid,
                    "status": pair.status.value if hasattr(pair.status, "value") else str(pair.status),
                    "user_id": pair.user_id,
                    "created_at": pair.created_at.isoformat() if hasattr(pair.created_at, "isoformat") else str(pair.created_at),
                })
    return result


@app.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["sessions"],
)
async def create_session(
    body: CreateSessionRequest,
    user: dict = Depends(get_current_user),
):
    """Create a new relay session.

    Returns the session ID that the browser and agent use to connect
    via the /ws endpoint.
    """
    assert _session_manager is not None

    session_id = str(uuid.uuid4())
    pair = await _session_manager.create_session(
        user_id=user["user_id"],
        session_id=session_id,
        title=body.title,
        model=body.model,
    )

    # Persist if store is available
    if _store:
        try:
            await _store.create_session(
                session_id=session_id,
                user_id=user["user_id"],
                title=body.title,
                model=body.model,
            )
        except Exception:
            logger.exception("relay.persist_create_failed", session_id=session_id)

    return _session_manager.to_dict(pair)


@app.get("/sessions", response_model=list[SessionResponse], tags=["sessions"])
async def list_sessions(
    user: dict = Depends(get_current_user),
):
    """List all active sessions for the current user."""
    assert _session_manager is not None

    # Prefer persisted data if available
    if _store:
        try:
            return await _store.list_sessions(user["user_id"])
        except Exception:
            logger.exception("relay.persist_list_failed")

    # Fall back to in-memory
    pairs = await _session_manager.list_sessions(user["user_id"])
    return [_session_manager.to_dict(p) for p in pairs]


@app.get("/sessions/{session_id}", response_model=SessionResponse, tags=["sessions"])
async def get_session(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Get details of a specific session."""
    assert _session_manager is not None

    pair = await _session_manager.get_session(session_id)
    if pair is None:
        # Try persisted store
        if _store:
            try:
                persisted = await _store.get_session(session_id)
                if persisted:
                    if str(persisted.get("user_id")) != user["user_id"]:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Session belongs to another user",
                        )
                    return persisted
            except HTTPException:
                raise
            except Exception:
                logger.exception("relay.persist_get_failed", session_id=session_id)

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    # Check ownership
    if pair.user_id != user["user_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session belongs to another user",
        )

    return _session_manager.to_dict(pair)


@app.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["sessions"])
async def delete_session(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Close and remove a session."""
    assert _session_manager is not None

    pair = await _session_manager.get_session(session_id)
    if pair is not None and pair.user_id != user["user_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session belongs to another user",
        )

    # Close in-memory
    await _session_manager.close_session(session_id)
    await _session_manager.remove_session(session_id)

    # Close persisted
    if _store:
        try:
            await _store.close_session(session_id)
        except Exception:
            logger.exception("relay.persist_close_failed", session_id=session_id)


@app.get(
    "/sessions/{session_id}/history",
    response_model=list[MessageResponse],
    tags=["sessions"],
)
async def get_session_history(
    session_id: str,
    limit: int = 200,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    """Get persisted message history for a session."""
    assert _session_manager is not None

    # Verify ownership
    pair = await _session_manager.get_session(session_id)
    if pair is not None and pair.user_id != user["user_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session belongs to another user",
        )

    if _store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Message persistence is not available",
        )

    try:
        return await _store.get_messages(session_id, limit=limit, offset=offset)
    except Exception:
        logger.exception("relay.persist_history_failed", session_id=session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve message history",
        )
