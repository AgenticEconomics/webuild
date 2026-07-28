"""Session manager — tracks active relay sessions and their WebSocket pairs.

Each session maps a browser (client) WebSocket to an agent WebSocket.
The SessionManager is the single source of truth for which connections
are currently paired.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class SessionStatus(str, Enum):
    WAITING_AGENT = "waiting_agent"   # browser connected, waiting for agent
    WAITING_CLIENT = "waiting_client" # agent connected, waiting for browser
    ACTIVE = "active"                 # both sides connected
    CLOSED = "closed"


@dataclass
class SessionPair:
    """A paired browser <-> agent session."""
    session_id: str
    user_id: str
    status: SessionStatus = SessionStatus.WAITING_AGENT
    browser_ws: Any = None  # fastapi.WebSocket (avoid circular import)
    agent_ws: Any = None
    title: str | None = None
    model: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Lock to serialize writes to each WebSocket
    browser_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    agent_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Ensure only one run_session loop owns the pair (browser+agent both try to start)
    routing_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    is_routing: bool = False

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


class SessionManager:
    """Thread-safe manager for relay session pairs.

    All public methods are async-safe (guarded by an internal lock).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionPair] = {}
        self._lock = asyncio.Lock()
        # Index: user_id -> set of session_ids
        self._user_index: dict[str, set[str]] = {}

    async def create_session(
        self,
        user_id: str,
        session_id: str | None = None,
        title: str | None = None,
        model: str | None = None,
    ) -> SessionPair:
        """Create a new session and return the pair (initially waiting for agent)."""
        sid = session_id or str(uuid.uuid4())
        async with self._lock:
            if sid in self._sessions:
                raise ValueError(f"Session {sid} already exists")
            pair = SessionPair(
                session_id=sid,
                user_id=user_id,
                status=SessionStatus.WAITING_AGENT,
                title=title,
                model=model,
            )
            self._sessions[sid] = pair
            self._user_index.setdefault(user_id, set()).add(sid)
            logger.info("session.created", session_id=sid, user_id=user_id)
            return pair

    async def get_session(self, session_id: str) -> SessionPair | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def list_sessions(self, user_id: str) -> list[SessionPair]:
        """Return all non-closed sessions for a user."""
        async with self._lock:
            ids = self._user_index.get(user_id, set())
            return [
                self._sessions[sid]
                for sid in ids
                if sid in self._sessions and self._sessions[sid].status != SessionStatus.CLOSED
            ]

    async def transfer_ownership(self, session_id: str, new_user_id: str) -> SessionPair | None:
        """Move a session to a different user (e.g. sandbox-agent → real user)."""
        async with self._lock:
            pair = self._sessions.get(session_id)
            if pair is None:
                return None
            old = pair.user_id
            if old == new_user_id:
                return pair
            pair.user_id = new_user_id
            pair.touch()
            old_set = self._user_index.get(old)
            if old_set:
                old_set.discard(session_id)
                if not old_set:
                    del self._user_index[old]
            self._user_index.setdefault(new_user_id, set()).add(session_id)
            logger.info(
                "session.ownership_transferred",
                session_id=session_id,
                from_user=old,
                to_user=new_user_id,
            )
            return pair

    async def register_browser(self, session_id: str, ws: Any) -> SessionPair | None:
        """Register a browser WebSocket for an existing or new session."""
        async with self._lock:
            pair = self._sessions.get(session_id)
            if pair is None:
                return None
            pair.browser_ws = ws
            pair.touch()
            if pair.agent_ws is not None:
                pair.status = SessionStatus.ACTIVE
            else:
                pair.status = SessionStatus.WAITING_AGENT
            logger.info("session.browser_registered", session_id=session_id)
            return pair

    async def register_agent(self, session_id: str, ws: Any) -> SessionPair | None:
        """Register an agent WebSocket for an existing session.

        If an agent is already actively routing, reject the newcomer so a late
        sandbox agent cannot steal the socket from the live lightweight agent
        (or vice versa).
        """
        async with self._lock:
            pair = self._sessions.get(session_id)
            if pair is None:
                return None
            if pair.agent_ws is not None and (
                pair.is_routing or pair.status == SessionStatus.ACTIVE
            ):
                logger.warning(
                    "session.agent_rejected_already_active",
                    session_id=session_id,
                )
                return None
            pair.agent_ws = ws
            pair.touch()
            if pair.browser_ws is not None:
                pair.status = SessionStatus.ACTIVE
            else:
                pair.status = SessionStatus.WAITING_CLIENT
            logger.info("session.agent_registered", session_id=session_id)
            return pair

    async def close_session(self, session_id: str) -> bool:
        """Mark a session as closed and clear its WebSocket references."""
        async with self._lock:
            pair = self._sessions.get(session_id)
            if pair is None:
                return False
            pair.status = SessionStatus.CLOSED
            pair.browser_ws = None
            pair.agent_ws = None
            pair.touch()
            logger.info("session.closed", session_id=session_id)
            return True

    async def remove_session(self, session_id: str) -> bool:
        """Remove a session entirely from the manager."""
        async with self._lock:
            pair = self._sessions.pop(session_id, None)
            if pair is None:
                return False
            user_sessions = self._user_index.get(pair.user_id)
            if user_sessions:
                user_sessions.discard(session_id)
                if not user_sessions:
                    del self._user_index[pair.user_id]
            logger.info("session.removed", session_id=session_id)
            return True

    async def get_active_count(self) -> int:
        async with self._lock:
            return sum(
                1 for p in self._sessions.values()
                if p.status == SessionStatus.ACTIVE
            )

    async def get_total_count(self) -> int:
        async with self._lock:
            return len(self._sessions)

    def to_dict(self, pair: SessionPair) -> dict[str, Any]:
        """Serialize a SessionPair for API responses."""
        return {
            "session_id": pair.session_id,
            "user_id": pair.user_id,
            "status": pair.status.value,
            "title": pair.title,
            "model": pair.model,
            "browser_connected": pair.browser_ws is not None,
            "agent_connected": pair.agent_ws is not None,
            "created_at": pair.created_at.isoformat(),
            "updated_at": pair.updated_at.isoformat(),
        }
