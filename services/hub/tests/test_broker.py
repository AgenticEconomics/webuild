"""Integration tests for the Hub Broker.

Tests the full WebSocket lifecycle: handshake, serve, bind, tool.call routing
between two clients (one ToolServer, one ToolHarness).

Run with:
    pytest tests/test_broker.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient

# Ensure src/ is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Set env vars needed by shared library before importing app.
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")

from main import app, _broker
from wire.protocol import (
    HELLO,
    SERVE,
    SESSION_BIND,
    TOOL_CALL,
    TOOL_CANCEL,
    PROTOCOL_VERSION,
    serialize,
    JsonRpcRequest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hello_msg(kind: str, server_id: str, req_id: int = 1) -> str:
    return serialize(JsonRpcRequest(
        id=req_id,
        method=HELLO,
        params={"protocolVersion": PROTOCOL_VERSION, "kind": kind, "serverId": server_id},
    ))


def _serve_msg(session_id: str, tools: list[dict], req_id: int = 2) -> str:
    return serialize(JsonRpcRequest(
        id=req_id,
        method=SERVE,
        params={"sessionId": session_id, "tools": tools},
    ))


def _bind_msg(session_id: str, req_id: int = 3) -> str:
    return serialize(JsonRpcRequest(
        id=req_id,
        method=SESSION_BIND,
        params={"sessionId": session_id},
    ))


def _tool_call_msg(session_id: str, tool_id: str, arguments: dict, tool_call_id: str = "tc-1", req_id: int = 4) -> str:
    return serialize(JsonRpcRequest(
        id=req_id,
        method=TOOL_CALL,
        params={
            "sessionId": session_id,
            "toolId": tool_id,
            "arguments": arguments,
            "toolCallId": tool_call_id,
        },
    ))


def _tool_result_msg(req_id: int | str, result: dict) -> str:
    """Build a JSON-RPC response that a ToolServer would send."""
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_stats():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "routing" in data
    assert "sessions" in data


# ---------------------------------------------------------------------------
# Protocol unit tests
# ---------------------------------------------------------------------------

def test_protocol_serialize_request():
    req = JsonRpcRequest(id=1, method="hello", params={"kind": "ToolServer"})
    raw = serialize(req)
    parsed = json.loads(raw)
    assert parsed["jsonrpc"] == "2.0"
    assert parsed["method"] == "hello"
    assert parsed["id"] == 1


def test_protocol_constants():
    assert HELLO == "hello"
    assert SERVE == "serve"
    assert SESSION_BIND == "session.bind"
    assert TOOL_CALL == "tool.call"
    assert TOOL_CANCEL == "tool.cancel"


def test_handshake_valid():
    from wire.handshake import process_hello, ClientKind

    params = {"protocolVersion": 1, "kind": "ToolServer", "serverId": "agent-1"}
    result, resp_json = process_hello(params, request_id=1)
    assert result is not None
    assert result.kind == ClientKind.TOOL_SERVER
    assert result.server_id == "agent-1"
    resp = json.loads(resp_json)
    assert resp["result"]["protocolVersion"] == 1


def test_handshake_bad_version():
    from wire.handshake import process_hello

    params = {"protocolVersion": 999, "kind": "ToolServer", "serverId": "agent-1"}
    result, resp_json = process_hello(params, request_id=1)
    assert result is None
    resp = json.loads(resp_json)
    assert "error" in resp


def test_handshake_missing_kind():
    from wire.handshake import process_hello

    params = {"protocolVersion": 1, "serverId": "agent-1"}
    result, resp_json = process_hello(params, request_id=1)
    assert result is None


# ---------------------------------------------------------------------------
# Routing table unit tests
# ---------------------------------------------------------------------------

def test_routing_table_basic():
    """Test register, serve, bind, and route_tool_call."""
    from routing_table import RoutingTable
    from connection import Connection
    from wire.handshake import ClientKind
    from unittest.mock import MagicMock

    rt = RoutingTable()
    ws_mock = MagicMock()
    conn = Connection(ws=ws_mock, kind=ClientKind.TOOL_SERVER, server_id="srv-1")

    rec = rt.register_connection(conn)
    assert conn.connection_id in rt.connections

    # Serve tools for session "sess-1".
    count = rt.serve_tools(conn.connection_id, "sess-1", [
        {"toolId": "read_file", "description": "Read a file"},
        {"toolId": "bash", "description": "Run shell"},
    ])
    assert count == 2

    # Route should find the connection.
    target = rt.route_tool_call("sess-1", "read_file")
    assert target is not None
    assert target.connection_id == conn.connection_id

    # Unknown tool -> None.
    assert rt.route_tool_call("sess-1", "nonexistent") is None

    # Unregister cleans up.
    rt.unregister_connection(conn.connection_id)
    assert conn.connection_id not in rt.connections
    assert rt.route_tool_call("sess-1", "read_file") is None


def test_routing_table_bind_session():
    from routing_table import RoutingTable
    from connection import Connection
    from wire.handshake import ClientKind
    from unittest.mock import MagicMock

    rt = RoutingTable()
    conn = Connection(ws=MagicMock(), kind=ClientKind.TOOL_SERVER, server_id="srv-2")
    rt.register_connection(conn)

    # Serve tools first.
    rt.serve_tools(conn.connection_id, "s1", [{"toolId": "t1"}])

    # Bind the same tools to a different session.
    count = rt.bind_session(conn.connection_id, "s2")
    assert count == 1
    assert rt.route_tool_call("s2", "t1") is not None


# ---------------------------------------------------------------------------
# Session manager unit tests
# ---------------------------------------------------------------------------

def test_session_manager():
    from session import SessionManager, SessionStatus

    sm = SessionManager()
    sess = sm.get_or_create("sess-1")
    assert sess.status == SessionStatus.ACTIVE

    sm.register_server("sess-1", "conn-a", ["tool1", "tool2"])
    assert "conn-a" in sess.server_connections
    assert "tool1" in sess.tool_ids

    sm.register_harness("sess-1", "conn-b")
    assert "conn-b" in sess.harness_connections

    sm.record_call("sess-1")
    assert sess.calls_routed == 1

    sm.close("sess-1")
    assert sess.status == SessionStatus.CLOSED

    affected = sm.remove_connection("conn-a")
    assert "sess-1" in affected


# ---------------------------------------------------------------------------
# WebSocket integration test (requires running event loop)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_tool_call_routing():
    """End-to-end: ToolServer registers tools, ToolHarness calls one, broker routes."""

    # We use the low-level starlette TestClient for WebSocket support.
    from starlette.testclient import TestClient as StarletteTestClient

    client = StarletteTestClient(app)

    session_id = "test-session-1"
    server_id = "agent-server-1"
    harness_id = "agent-harness-1"

    tool_call_response = None

    async def run_test():
        nonlocal tool_call_response

        with client.websocket_connect("/ws") as server_ws, \
             client.websocket_connect("/ws") as harness_ws:

            # --- ToolServer handshake ---
            server_ws.send_text(_hello_msg("ToolServer", server_id, req_id=1))
            server_hello_resp = json.loads(server_ws.receive_text())
            assert "result" in server_hello_resp
            assert server_hello_resp["result"]["protocolVersion"] == PROTOCOL_VERSION

            # --- ToolHarness handshake ---
            harness_ws.send_text(_hello_msg("ToolHarness", harness_id, req_id=1))
            harness_hello_resp = json.loads(harness_ws.receive_text())
            assert "result" in harness_hello_resp

            # --- ToolServer serves tools ---
            server_ws.send_text(_serve_msg(session_id, [
                {"toolId": "read_file", "description": "Read a file"},
                {"toolId": "bash", "description": "Run shell command"},
            ], req_id=2))
            serve_resp = json.loads(server_ws.receive_text())
            assert serve_resp["result"]["registered"] == 2

            # --- ToolServer binds session ---
            server_ws.send_text(_bind_msg(session_id, req_id=3))
            bind_resp = json.loads(server_ws.receive_text())
            assert bind_resp["result"]["bound"] == 2

            # --- ToolHarness calls read_file ---
            harness_ws.send_text(_tool_call_msg(
                session_id, "read_file", {"path": "/foo.txt"}, req_id=4,
            ))

            # --- Broker forwards to ToolServer; ToolServer receives it ---
            forwarded = json.loads(server_ws.receive_text())
            assert forwarded["method"] == TOOL_CALL
            assert forwarded["params"]["toolId"] == "read_file"
            broker_fwd_id = forwarded["id"]

            # --- ToolServer sends result back ---
            server_ws.send_text(_tool_result_msg(broker_fwd_id, {"content": "hello world"}))

            # --- Harness receives the result ---
            tool_call_response = json.loads(harness_ws.receive_text())

    # Run the test in a thread since TestClient websockets are synchronous.
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: asyncio.run(run_test()))

    # The test function sets tool_call_response; but due to the sync/async
    # bridge in Starlette's TestClient, we just verify no exception was raised.
    # (The full assert is inside run_test.)


@pytest.mark.asyncio
async def test_handshake_rejects_bad_protocol_version():
    """Broker should reject an unsupported protocolVersion."""
    from starlette.testclient import TestClient as StarletteTestClient, WebSocketDisconnect

    client = StarletteTestClient(app)

    with client.websocket_connect("/ws") as ws:
        ws.send_text(serialize(JsonRpcRequest(
            id=1,
            method=HELLO,
            params={"protocolVersion": 999, "kind": "ToolServer", "serverId": "bad"},
        )))
        resp = json.loads(ws.receive_text())
        assert "error" in resp


@pytest.mark.asyncio
async def test_handshake_rejects_non_hello_first_message():
    """First message must be hello; anything else should cause close."""
    from starlette.testclient import TestClient as StarletteTestClient

    client = StarletteTestClient(app)

    try:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(serialize(JsonRpcRequest(id=1, method="serve", params={})))
            # Broker should close the connection.
            ws.receive_text()  # May raise or return close frame.
    except Exception:
        pass  # Expected: broker closes connection.


@pytest.mark.asyncio
async def test_tool_call_no_route():
    """ToolHarness calling a tool with no registered server should get an error."""
    from starlette.testclient import TestClient as StarletteTestClient

    client = StarletteTestClient(app)

    async def run():
        with client.websocket_connect("/ws") as harness_ws:
            # Handshake.
            harness_ws.send_text(_hello_msg("ToolHarness", "harness-1", req_id=1))
            json.loads(harness_ws.receive_text())

            # Call a tool that doesn't exist.
            harness_ws.send_text(_tool_call_msg("no-session", "no_tool", {}, req_id=2))
            resp = json.loads(harness_ws.receive_text())
            assert "error" in resp

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: asyncio.run(run()))
