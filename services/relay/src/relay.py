"""WebSocket endpoint handler for ACP relay.

Handles the /ws endpoint:
  - Authenticates via Bearer token (query param or first message)
  - Routes connections as either "browser" (client) or "agent" based on role param
  - Pairs connections by session_id and starts bidirectional forwarding
  - Implements ping/pong keepalive
  - Cleans up on disconnect
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status

from webuild_shared.jwt import JWTManager

from src.acp.protocol import make_error_response, INTERNAL_ERROR, PARSE_ERROR
from src.acp.router import AcpRouter
from src.persistence import SessionStore
from src.session_manager import SessionManager, SessionPair, SessionStatus

logger = structlog.get_logger()

ws_router = APIRouter()

# These are injected at app startup (see main.py)
_session_manager: SessionManager | None = None
_router: AcpRouter | None = None
_store: SessionStore | None = None
_jwt: JWTManager | None = None

# Keepalive interval (seconds)
PING_INTERVAL = 30


def init_relay(
    session_manager: SessionManager,
    router: AcpRouter,
    store: SessionStore | None,
    jwt_manager: JWTManager,
) -> None:
    """Wire up dependencies — called once at app startup."""
    global _session_manager, _router, _store, _jwt
    _session_manager = session_manager
    _router = router
    _store = store
    _jwt = jwt_manager


def _authenticate(token: str) -> dict[str, Any] | None:
    """Verify a Bearer token and return user info or None."""
    if _jwt is None:
        return None
    try:
        payload = _jwt.verify_token(token, expected_type="access")
        return {"user_id": payload.sub, "scopes": payload.scopes}
    except Exception:
        return None


async def _keepalive(ws: WebSocket, session_id: str, role: str) -> None:
    """Send periodic pings to keep the WebSocket alive."""
    try:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await ws.send_text(json.dumps({"jsonrpc": "2.0", "method": "__ping"}))
    except (WebSocketDisconnect, asyncio.CancelledError, Exception):
        pass


async def _wait_for_pair(
    session_id: str,
    pair: SessionPair,
    timeout: float = 120.0,
) -> bool:
    """Wait until both browser and agent are connected, or timeout.

    Default 120s — long enough for agent /discover polling, short enough
    to avoid zombie agents camping on abandoned sessions for 5 minutes.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if pair.browser_ws is not None and pair.agent_ws is not None:
            return True
        # Bail early if the waiting side already dropped
        if pair.status == SessionStatus.CLOSED:
            return False
        await asyncio.sleep(0.5)
    return False


@ws_router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    session_id: str = Query(default=""),
    role: str = Query(default="browser"),
    token: str = Query(default=""),
    user_id: str = Query(default=""),
) -> None:
    """Main WebSocket endpoint for ACP relay.

    Query parameters:
      - session_id: the relay session to join (required)
      - role: "browser" (client) or "agent"
      - token: Bearer token (alternative to Authorization header)
      - user_id: optional real user id for internal sandbox agents
    """
    assert _session_manager is not None, "relay not initialized"
    assert _router is not None, "relay not initialized"

    # --- Authenticate ---
    user = None

    # Prefer query token; also accept Authorization: Bearer (Rust CLI client)
    auth_header = ws.headers.get("authorization") or ws.headers.get("Authorization") or ""
    header_token = ""
    if auth_header.lower().startswith("bearer "):
        header_token = auth_header[7:].strip()
    effective_token = token or header_token

    # Allow internal agent token for sandbox agents (bypasses JWT)
    internal_token = os.environ.get("RELAY_INTERNAL_TOKEN", "")
    if internal_token and effective_token == internal_token and role == "agent":
        # Prefer the real user id passed by the sandbox pod when available
        effective_user = user_id.strip() if user_id else "sandbox-agent"
        user = {"user_id": effective_user, "scopes": ["agent.use"]}
        logger.info("ws.internal_agent_auth", session_id=session_id, user_id=effective_user)
    elif effective_token:
        user = _authenticate(effective_token)

    if user is None:
        # Try the first message as an auth envelope
        await ws.accept()
        try:
            first_raw = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
            first_msg = json.loads(first_raw)
            auth_token = first_msg.get("token") or first_msg.get("auth")
            if auth_token:
                user = _authenticate(str(auth_token))
        except Exception:
            pass

        if user is None:
            await ws.send_text(
                make_error_response(None, INTERNAL_ERROR, "Authentication required")
            )
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    else:
        await ws.accept()

    user_id = user["user_id"]
    logger.info(
        "ws.authenticated",
        session_id=session_id,
        role=role,
        user_id=user_id,
    )

    # --- Resolve or create session ---
    if not session_id:
        await ws.send_text(
            make_error_response(None, INTERNAL_ERROR, "session_id is required")
        )
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    pair = await _session_manager.get_session(session_id)

    if role == "browser":
        if pair is None:
            # Auto-create session for browser
            pair = await _session_manager.create_session(
                user_id=user_id, session_id=session_id
            )
            if _store:
                try:
                    await _store.create_session(session_id, user_id)
                except Exception:
                    # Already persisted (e.g. reopening an old session)
                    logger.info("ws.persist_create_skipped", session_id=session_id)
                    await _store.update_status(session_id, "waiting_agent")
            pair = await _session_manager.register_browser(session_id, ws)
        else:
            # Reopen a previously closed in-memory session
            if pair.status == SessionStatus.CLOSED:
                pair.status = SessionStatus.WAITING_AGENT
                if _store:
                    await _store.update_status(session_id, "waiting_agent")
            # Sandbox agents often create the session first with user_id=sandbox-agent;
            # adopt the real browser user so the session appears in their sidebar.
            if pair.user_id in ("sandbox-agent", "agent") and user_id not in ("sandbox-agent", "agent"):
                await _session_manager.transfer_ownership(session_id, user_id)
                if _store:
                    try:
                        await _store.update_user(session_id, user_id)
                    except Exception:
                        logger.exception("ws.persist_ownership_failed", session_id=session_id)
            pair = await _session_manager.register_browser(session_id, ws)

        if pair is None:
            await ws.send_text(
                make_error_response(None, INTERNAL_ERROR, "Failed to register browser")
            )
            await ws.close(code=status.WS_1011_INTERNAL_ERROR)
            return

    elif role == "agent":
        if pair is None:
            # Auto-create session for agent (sandbox agents connect before browser)
            pair = await _session_manager.create_session(
                user_id=user_id, session_id=session_id
            )
            if _store:
                try:
                    await _store.create_session(session_id, user_id)
                except Exception:
                    logger.info("ws.persist_create_skipped", session_id=session_id)
                    await _store.update_status(session_id, "waiting_client")
            logger.info("ws.agent_created_session", session_id=session_id)
        elif pair.status == SessionStatus.CLOSED:
            pair.status = SessionStatus.WAITING_CLIENT
            if _store:
                await _store.update_status(session_id, "waiting_client")

        pair = await _session_manager.register_agent(session_id, ws)
        if pair is None:
            await ws.send_text(
                make_error_response(
                    None,
                    INTERNAL_ERROR,
                    "Agent already active for this session",
                )
            )
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    else:
        await ws.send_text(
            make_error_response(None, INTERNAL_ERROR, f"Unknown role: {role}")
        )
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # --- Start keepalive ---
    keepalive_task = asyncio.create_task(_keepalive(ws, session_id, role))

    try:
        if pair.status == SessionStatus.ACTIVE:
            # Both sides are connected — start bidirectional forwarding
            await _router.run_session(session_id, pair)
        else:
            # Wait for the other side to connect
            # Keep reading from our WebSocket while waiting so we don't block
            connected = await _wait_for_pair(session_id, pair)
            if connected and _router is not None:
                await _router.run_session(session_id, pair)
            else:
                logger.info(
                    "ws.pair_timeout",
                    session_id=session_id,
                    role=role,
                )
    except WebSocketDisconnect:
        logger.info("ws.disconnected", session_id=session_id, role=role)
    except Exception as exc:
        logger.exception(
            "ws.error",
            session_id=session_id,
            role=role,
            error=str(exc),
        )
    finally:
        keepalive_task.cancel()
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass

        # Clean up
        if role == "browser":
            pair.browser_ws = None
        elif role == "agent":
            pair.agent_ws = None

        if pair.browser_ws is None and pair.agent_ws is None:
            pair.status = SessionStatus.CLOSED
            if _store:
                await _store.close_session(session_id)
            logger.info("ws.session_fully_closed", session_id=session_id)
