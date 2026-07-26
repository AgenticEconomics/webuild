"""JSON-RPC 2.0 wire protocol for the Hub Broker.

All messages on the wire are text WebSocket frames carrying JSON-RPC 2.0
envelopes.  This module defines the envelope types, method-string constants,
and thin parse / serialize helpers.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Method constants
# ---------------------------------------------------------------------------

class Method(str, Enum):
    """JSON-RPC method strings used on the Hub wire."""

    HELLO = "hello"
    SERVE = "serve"
    SESSION_BIND = "session.bind"
    TOOL_CALL = "tool.call"
    TOOL_CANCEL = "tool.cancel"
    TOOL_HOOK = "tool.hook"
    TOOL_HOOK_REQUEST = "tool.hook_request"


# Re-export as plain strings for convenient comparison / logging.
HELLO: str = Method.HELLO.value
SERVE: str = Method.SERVE.value
SESSION_BIND: str = Method.SESSION_BIND.value
TOOL_CALL: str = Method.TOOL_CALL.value
TOOL_CANCEL: str = Method.TOOL_CANCEL.value
TOOL_HOOK: str = Method.TOOL_HOOK.value
TOOL_HOOK_REQUEST: str = Method.TOOL_HOOK_REQUEST.value

# Current protocol version the broker speaks.
PROTOCOL_VERSION: int = 1


# ---------------------------------------------------------------------------
# Envelope data-classes
# ---------------------------------------------------------------------------

@dataclass
class JsonRpcRequest:
    """A JSON-RPC 2.0 *request* (expects a response)."""

    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: int | str | None = None
    jsonrpc: str = "2.0"

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = _next_id()


@dataclass
class JsonRpcNotification:
    """A JSON-RPC 2.0 *notification* (no response expected)."""

    method: str
    params: dict[str, Any] = field(default_factory=dict)
    jsonrpc: str = "2.0"


@dataclass
class JsonRpcResponse:
    """A JSON-RPC 2.0 *response*."""

    id: int | str | None
    result: Any = None
    error: dict[str, Any] | None = None
    jsonrpc: str = "2.0"

    @property
    def is_error(self) -> bool:
        return self.error is not None


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def serialize(msg: JsonRpcRequest | JsonRpcNotification | JsonRpcResponse) -> str:
    """Serialize an envelope to a JSON string suitable for a text WS frame."""
    d = asdict(msg)
    # Notifications must NOT carry an "id" key.
    if isinstance(msg, JsonRpcNotification):
        d.pop("id", None)
    # Drop ``None`` values to keep the wire representation compact.
    d = {k: v for k, v in d.items() if v is not None}
    return json.dumps(d)


def deserialize(raw: str) -> dict[str, Any]:
    """Parse a raw text frame into a plain dict.

    Returns the parsed JSON dict.  Callers should inspect the ``method`` key
    to decide whether the message is a request/notification or use ``id`` /
    ``result`` / ``error`` keys for a response.

    Raises ``ValueError`` for non-JSON-RPC or malformed payloads.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("JSON-RPC envelope must be a JSON object")
    if data.get("jsonrpc") != "2.0":
        raise ValueError("Missing or invalid jsonrpc field (must be '2.0')")
    return data


def make_response(
    request_id: int | str | None,
    result: Any = None,
    error: dict[str, Any] | None = None,
) -> str:
    """Convenience: build and serialize a JSON-RPC response."""
    return serialize(JsonRpcResponse(id=request_id, result=result, error=error))


def make_error(request_id: int | str | None, code: int, message: str, data: Any = None) -> str:
    """Convenience: build and serialize a JSON-RPC error response."""
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return make_response(request_id, error=err)


# Standard JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_id_counter: int = 0


def _next_id() -> str:
    """Generate a unique request id (broker-side)."""
    global _id_counter
    _id_counter += 1
    return f"broker-{_id_counter}-{uuid.uuid4().hex[:8]}"
