"""Hello-handshake logic for the Hub Broker.

When a new WebSocket client connects, both sides exchange a ``hello`` message.
This module validates the client's hello and builds the broker's response.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog

from wire.protocol import (
    HELLO,
    PROTOCOL_VERSION,
    JsonRpcResponse,
    make_error,
    make_response,
    INVALID_PARAMS,
)

log = structlog.get_logger(__name__)


class ClientKind(str, Enum):
    """The role a connecting client declares."""

    TOOL_SERVER = "ToolServer"
    TOOL_HARNESS = "ToolHarness"


@dataclass
class HandshakeResult:
    """Outcome of processing a client hello."""

    kind: ClientKind
    server_id: str
    protocol_version: int


def process_hello(raw_params: dict[str, Any], request_id: int | str | None) -> tuple[HandshakeResult | None, str]:
    """Validate a ``hello`` request and return (result, response_json).

    If validation fails *result* is ``None`` and *response_json* carries an
    error envelope.
    """
    # -- protocolVersion ---------------------------------------------------
    proto_ver = raw_params.get("protocolVersion")
    if proto_ver is None:
        return None, make_error(request_id, INVALID_PARAMS, "Missing protocolVersion")
    if proto_ver != PROTOCOL_VERSION:
        return None, make_error(
            request_id,
            INVALID_PARAMS,
            f"Unsupported protocolVersion {proto_ver} (broker speaks {PROTOCOL_VERSION})",
        )

    # -- kind --------------------------------------------------------------
    raw_kind = raw_params.get("kind")
    if raw_kind is None:
        return None, make_error(request_id, INVALID_PARAMS, "Missing kind")
    try:
        kind = ClientKind(raw_kind)
    except ValueError:
        return None, make_error(
            request_id,
            INVALID_PARAMS,
            f"Invalid kind '{raw_kind}' (expected ToolServer or ToolHarness)",
        )

    # -- serverId ----------------------------------------------------------
    server_id = raw_params.get("serverId")
    if not server_id or not isinstance(server_id, str):
        return None, make_error(request_id, INVALID_PARAMS, "Missing or invalid serverId")

    log.info("hello_ok", kind=kind.value, server_id=server_id)

    result = HandshakeResult(kind=kind, server_id=server_id, protocol_version=proto_ver)
    response = make_response(
        request_id,
        result={"protocolVersion": PROTOCOL_VERSION, "serverId": f"hub-broker-{server_id[:8]}"},
    )
    return result, response
