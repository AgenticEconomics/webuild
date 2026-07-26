"""Routing table for the Hub Broker.

Maps (session_id, tool_id) pairs to the ToolServer Connection that should
receive the ``tool.call``.  Also tracks per-connection metadata such as
registered tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from connection import Connection

log = structlog.get_logger(__name__)


@dataclass
class ToolDescriptor:
    """Lightweight description of a single tool registered by a ToolServer."""

    tool_id: str
    description: str = ""


@dataclass
class ConnectionRecord:
    """Everything the routing table knows about a single connection."""

    connection: Connection
    tools: dict[str, ToolDescriptor] = field(default_factory=dict)
    sessions: set[str] = field(default_factory=set)


class RoutingTable:
    """In-memory routing state.

    Thread-safety: this class is *not* thread-safe; all access is expected
    from the same asyncio event-loop.
    """

    def __init__(self) -> None:
        # connection_id -> ConnectionRecord
        self.connections: dict[str, ConnectionRecord] = {}
        # (session_id, tool_id) -> connection_id
        self.session_bindings: dict[tuple[str, str], str] = {}

    # -- lifecycle ----------------------------------------------------------

    def register_connection(self, conn: Connection) -> ConnectionRecord:
        """Register a freshly-handshaken connection."""
        rec = ConnectionRecord(connection=conn)
        self.connections[conn.connection_id] = rec
        log.info("conn_registered", connection_id=conn.connection_id, kind=conn.kind and conn.kind.value)
        return rec

    def unregister_connection(self, connection_id: str) -> None:
        """Remove a connection and all its routing state."""
        rec = self.connections.pop(connection_id, None)
        if rec is None:
            return

        # Remove session bindings that pointed at this connection.
        stale_keys = [
            k for k, v in self.session_bindings.items() if v == connection_id
        ]
        for k in stale_keys:
            del self.session_bindings[k]

        log.info(
            "conn_unregistered",
            connection_id=connection_id,
            removed_bindings=len(stale_keys),
            tools=len(rec.tools),
        )

    # -- tool registration --------------------------------------------------

    def serve_tools(
        self,
        connection_id: str,
        session_id: str,
        tools: list[dict[str, Any]],
    ) -> int:
        """Register tools advertised by a ToolServer for *session_id*.

        Returns the number of tools registered.
        """
        rec = self.connections.get(connection_id)
        if rec is None:
            raise KeyError(f"Unknown connection_id {connection_id}")

        rec.sessions.add(session_id)
        count = 0
        for t in tools:
            tid = t.get("toolId", "")
            if not tid:
                continue
            desc = ToolDescriptor(tool_id=tid, description=t.get("description", ""))
            rec.tools[tid] = desc
            # Create a default binding: (session, tool) -> this connection.
            self.session_bindings[(session_id, tid)] = connection_id
            count += 1

        log.info(
            "tools_served",
            connection_id=connection_id,
            session_id=session_id,
            count=count,
        )
        return count

    # -- session binding ----------------------------------------------------

    def bind_session(self, connection_id: str, session_id: str) -> int:
        """Explicitly bind all tools of *connection_id* to *session_id*.

        Returns the number of bindings created/updated.
        """
        rec = self.connections.get(connection_id)
        if rec is None:
            raise KeyError(f"Unknown connection_id {connection_id}")

        rec.sessions.add(session_id)
        count = 0
        for tid in rec.tools:
            self.session_bindings[(session_id, tid)] = connection_id
            count += 1

        log.info(
            "session_bound",
            connection_id=connection_id,
            session_id=session_id,
            tools=count,
        )
        return count

    # -- routing ------------------------------------------------------------

    def route_tool_call(self, session_id: str, tool_id: str) -> Connection | None:
        """Look up which Connection should handle a tool.call.

        Returns ``None`` when no route is found.
        """
        conn_id = self.session_bindings.get((session_id, tool_id))
        if conn_id is None:
            log.warning("route_miss", session_id=session_id, tool_id=tool_id)
            return None
        rec = self.connections.get(conn_id)
        if rec is None:
            # Stale binding -- clean up and report miss.
            del self.session_bindings[(session_id, tool_id)]
            log.warning("route_stale", session_id=session_id, tool_id=tool_id, stale_conn=conn_id)
            return None
        log.debug("route_hit", session_id=session_id, tool_id=tool_id, connection_id=conn_id)
        return rec.connection

    # -- introspection ------------------------------------------------------

    def get_registered_tools(self, session_id: str) -> list[ToolDescriptor]:
        """Return all tools currently routable for *session_id*."""
        seen: dict[str, ToolDescriptor] = {}
        for (sid, tid), conn_id in self.session_bindings.items():
            if sid != session_id:
                continue
            rec = self.connections.get(conn_id)
            if rec and tid in rec.tools:
                seen[tid] = rec.tools[tid]
        return list(seen.values())

    def stats(self) -> dict[str, int]:
        return {
            "connections": len(self.connections),
            "bindings": len(self.session_bindings),
        }
