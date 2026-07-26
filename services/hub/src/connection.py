"""Connection wrapper for a WebSocket client connected to the Hub Broker."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from fastapi import WebSocket

from wire.handshake import ClientKind

log = structlog.get_logger(__name__)


@dataclass
class Connection:
    """Represents a single authenticated WebSocket connection."""

    ws: WebSocket
    connection_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    kind: ClientKind | None = None
    server_id: str | None = None
    user_id: str | None = None

    # Book-keeping: ids of requests we forwarded *to* this connection and
    # are still waiting for a response on.  Maps remote-request-id -> asyncio.Future.
    pending: dict[str | int, Any] = field(default_factory=dict)

    # Semaphore controlling max concurrent tool calls routed *to* this
    # ToolServer connection.  Set by the broker after handshake.
    max_concurrent: int = 64

    async def send_json(self, raw: str) -> None:
        """Send a text frame (pre-serialized JSON)."""
        await self.ws.send_text(raw)

    def __hash__(self) -> int:
        return hash(self.connection_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Connection):
            return NotImplemented
        return self.connection_id == other.connection_id
