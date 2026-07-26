"""Session state tracking for the Hub Broker.

A *session* is a logical grouping that links one or more ToolServers with
one or more ToolHarnesses.  Sessions are identified by a ``sessionId``
string that appears in ``serve``, ``session.bind``, and ``tool.call``
messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

log = structlog.get_logger(__name__)


class SessionStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass
class SessionState:
    """Mutable state for a single session."""

    session_id: str
    status: SessionStatus = SessionStatus.ACTIVE

    # connection_ids of ToolServers serving this session.
    server_connections: set[str] = field(default_factory=set)

    # connection_ids of ToolHarnesses bound to this session.
    harness_connections: set[str] = field(default_factory=set)

    # Tool ids currently registered for this session.
    tool_ids: set[str] = field(default_factory=set)

    # Counters for observability.
    calls_routed: int = 0
    calls_cancelled: int = 0


class SessionManager:
    """Manages session lifecycle."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
            log.info("session_created", session_id=session_id)
        return self._sessions[session_id]

    def get(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def close(self, session_id: str) -> None:
        sess = self._sessions.get(session_id)
        if sess:
            sess.status = SessionStatus.CLOSED
            log.info("session_closed", session_id=session_id, calls_routed=sess.calls_routed)

    def remove_connection(self, connection_id: str) -> list[str]:
        """Remove a connection from all sessions. Returns affected session ids."""
        affected: list[str] = []
        for sid, sess in self._sessions.items():
            if connection_id in sess.server_connections:
                sess.server_connections.discard(connection_id)
                affected.append(sid)
            if connection_id in sess.harness_connections:
                sess.harness_connections.discard(connection_id)
                if sid not in affected:
                    affected.append(sid)
        return affected

    def register_server(self, session_id: str, connection_id: str, tool_ids: list[str]) -> None:
        sess = self.get_or_create(session_id)
        sess.server_connections.add(connection_id)
        sess.tool_ids.update(tool_ids)

    def register_harness(self, session_id: str, connection_id: str) -> None:
        sess = self.get_or_create(session_id)
        sess.harness_connections.add(connection_id)

    def record_call(self, session_id: str) -> None:
        sess = self._sessions.get(session_id)
        if sess:
            sess.calls_routed += 1

    def record_cancel(self, session_id: str) -> None:
        sess = self._sessions.get(session_id)
        if sess:
            sess.calls_cancelled += 1

    def active_sessions(self) -> list[SessionState]:
        return [s for s in self._sessions.values() if s.status == SessionStatus.ACTIVE]

    def stats(self) -> dict[str, Any]:
        active = self.active_sessions()
        return {
            "total_sessions": len(self._sessions),
            "active_sessions": len(active),
            "total_calls_routed": sum(s.calls_routed for s in self._sessions.values()),
        }
