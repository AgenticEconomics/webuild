"""ACP (Agent Client Protocol) JSON-RPC 2.0 wire format dataclasses.

The ACP transport uses text WebSocket frames carrying JSON-RPC 2.0 messages
(one message per frame). All field names use camelCase per serde rename_all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# ACP method constants
# ---------------------------------------------------------------------------

class ClientMethod(str, Enum):
    """Methods sent from browser (client) to agent."""
    INITIALIZE = "initialize"
    AUTHENTICATE = "authenticate"
    SESSION_NEW = "session/new"
    SESSION_LOAD = "session/load"
    SESSION_PROMPT = "session/prompt"
    SESSION_CANCEL = "session/cancel"
    SESSION_SET_MODEL = "session/set_model"
    SESSION_SET_MODE = "session/set_mode"
    SESSION_LIST = "session/list"


class AgentMethod(str, Enum):
    """Methods sent from agent to browser (client)."""
    SESSION_UPDATE = "session/update"
    SESSION_REQUEST_PERMISSION = "session/request_permission"
    TERMINAL_CREATE = "terminal/create"
    TERMINAL_OUTPUT = "terminal/output"
    TERMINAL_RELEASE = "terminal/release"
    TERMINAL_WAIT_FOR_EXIT = "terminal/wait_for_exit"
    TERMINAL_KILL = "terminal/kill"
    FS_READ_TEXT_FILE = "fs/read_text_file"
    FS_WRITE_TEXT_FILE = "fs/write_text_file"


# All known ACP methods (for validation)
ALL_CLIENT_METHODS = {m.value for m in ClientMethod}
ALL_AGENT_METHODS = {m.value for m in AgentMethod}
ALL_METHODS = ALL_CLIENT_METHODS | ALL_AGENT_METHODS


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 envelope types
# ---------------------------------------------------------------------------

@dataclass
class JsonRpcRequest:
    """A JSON-RPC 2.0 request (has an id, expects a response)."""
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: int | str | None = None
    jsonrpc: str = "2.0"
    meta: dict[str, Any] | None = None  # serialized as _meta

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.params:
            d["params"] = self.params
        if self.id is not None:
            d["id"] = self.id
        if self.meta is not None:
            d["_meta"] = self.meta
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JsonRpcRequest":
        return cls(
            method=data["method"],
            params=data.get("params", {}),
            id=data.get("id"),
            jsonrpc=data.get("jsonrpc", "2.0"),
            meta=data.get("_meta"),
        )


@dataclass
class JsonRpcResponse:
    """A JSON-RPC 2.0 response to a request."""
    id: int | str | None = None
    result: Any = None
    error: dict[str, Any] | None = None
    jsonrpc: str = "2.0"
    meta: dict[str, Any] | None = None  # serialized as _meta

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            d["error"] = self.error
        else:
            d["result"] = self.result
        if self.meta is not None:
            d["_meta"] = self.meta
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JsonRpcResponse":
        return cls(
            id=data.get("id"),
            result=data.get("result"),
            error=data.get("error"),
            jsonrpc=data.get("jsonrpc", "2.0"),
            meta=data.get("_meta"),
        )


@dataclass
class JsonRpcNotification:
    """A JSON-RPC 2.0 notification (no id, no response expected)."""
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    jsonrpc: str = "2.0"
    meta: dict[str, Any] | None = None  # serialized as _meta

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.params:
            d["params"] = self.params
        if self.meta is not None:
            d["_meta"] = self.meta
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JsonRpcNotification":
        return cls(
            method=data["method"],
            params=data.get("params", {}),
            jsonrpc=data.get("jsonrpc", "2.0"),
            meta=data.get("_meta"),
        )


@dataclass
class JsonRpcError:
    """A JSON-RPC 2.0 error object (used inside JsonRpcResponse.error)."""
    code: int
    message: str
    data: Any = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            d["data"] = self.data
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JsonRpcError":
        return cls(
            code=data["code"],
            message=data["message"],
            data=data.get("data"),
        )


# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# Parse / serialize helpers
# ---------------------------------------------------------------------------

def parse_message(raw: str) -> JsonRpcRequest | JsonRpcResponse | JsonRpcNotification:
    """Parse a raw JSON text frame into the appropriate JSON-RPC object.

    Raises ValueError on invalid JSON or missing required fields.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("JSON-RPC message must be a JSON object")

    if data.get("jsonrpc") != "2.0":
        raise ValueError(f"Expected jsonrpc '2.0', got {data.get('jsonrpc')!r}")

    # Notification: has method, no id
    if "method" in data and "id" not in data:
        return JsonRpcNotification.from_dict(data)

    # Request: has method and id
    if "method" in data and "id" in data:
        return JsonRpcRequest.from_dict(data)

    # Response: has id but no method
    if "id" in data:
        return JsonRpcResponse.from_dict(data)

    raise ValueError("Cannot determine JSON-RPC message type: missing method and id")


def serialize_message(
    msg: JsonRpcRequest | JsonRpcResponse | JsonRpcNotification,
) -> str:
    """Serialize a JSON-RPC message to a compact JSON string."""
    return msg.to_json()


def make_error_response(
    request_id: int | str | None,
    code: int,
    message: str,
    data: Any = None,
) -> str:
    """Build a JSON-RPC error response string."""
    return JsonRpcResponse(
        id=request_id,
        error=JsonRpcError(code=code, message=message, data=data).to_dict(),
    ).to_json()


def extract_session_id(msg: JsonRpcRequest | JsonRpcNotification) -> str | None:
    """Extract session_id from a message's params or _meta field.

    The ACP protocol nests session identifiers inside params. We check
    several common locations:
      - params.sessionId  (camelCase, serde default)
      - params.session_id
      - _meta.sessionId
    """
    params = getattr(msg, "params", {}) or {}
    for key in ("sessionId", "session_id"):
        if key in params and params[key]:
            return str(params[key])

    meta = getattr(msg, "meta", None) or {}
    for key in ("sessionId", "session_id"):
        if key in meta and meta[key]:
            return str(meta[key])

    return None
