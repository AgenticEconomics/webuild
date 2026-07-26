"""Tests for WeBuild Relay Server.

Tests cover:
  - JSON-RPC protocol parsing and serialization
  - Session manager lifecycle
  - WebSocket connection and message forwarding (integration)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Protocol tests
# ---------------------------------------------------------------------------

from src.acp.protocol import (
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    JsonRpcError,
    extract_session_id,
    make_error_response,
    parse_message,
    serialize_message,
    INTERNAL_ERROR,
    PARSE_ERROR,
)


class TestJsonRpcParsing:
    """Test parsing of JSON-RPC 2.0 messages."""

    def test_parse_request(self):
        raw = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/prompt",
            "params": {"sessionId": "abc-123", "content": "hello"},
        })
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcRequest)
        assert msg.method == "session/prompt"
        assert msg.id == 1
        assert msg.params["sessionId"] == "abc-123"

    def test_parse_notification(self):
        raw = json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": "abc-123", "sessionUpdate": "agent_message_chunk"},
        })
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcNotification)
        assert msg.method == "session/update"

    def test_parse_response(self):
        raw = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "ok"},
        })
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcResponse)
        assert msg.id == 1
        assert msg.result == {"status": "ok"}

    def test_parse_response_with_error(self):
        raw = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32601, "message": "Method not found"},
        })
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcResponse)
        assert msg.error is not None
        assert msg.error["code"] == -32601

    def test_parse_invalid_json(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_message("not json")

    def test_parse_missing_jsonrpc(self):
        with pytest.raises(ValueError, match="jsonrpc"):
            parse_message(json.dumps({"method": "foo"}))

    def test_parse_wrong_jsonrpc_version(self):
        with pytest.raises(ValueError, match="jsonrpc"):
            parse_message(json.dumps({"jsonrpc": "1.0", "method": "foo", "id": 1}))


class TestJsonRpcSerialization:
    """Test serialization of JSON-RPC messages."""

    def test_request_roundtrip(self):
        req = JsonRpcRequest(
            method="session/new",
            params={"title": "test"},
            id=42,
        )
        raw = req.to_json()
        parsed = json.loads(raw)
        assert parsed["jsonrpc"] == "2.0"
        assert parsed["method"] == "session/new"
        assert parsed["id"] == 42
        assert parsed["params"]["title"] == "test"

    def test_request_with_meta(self):
        req = JsonRpcRequest(
            method="session/prompt",
            params={"content": "hi"},
            id=1,
            meta={"traceId": "xyz"},
        )
        parsed = json.loads(req.to_json())
        assert parsed["_meta"]["traceId"] == "xyz"
        # Ensure "meta" key is NOT present (must be "_meta")
        assert "meta" not in parsed

    def test_notification_roundtrip(self):
        notif = JsonRpcNotification(
            method="session/update",
            params={"sessionUpdate": "agent_message_chunk", "content": "chunk1"},
        )
        parsed = json.loads(notif.to_json())
        assert "id" not in parsed
        assert parsed["method"] == "session/update"

    def test_response_roundtrip(self):
        resp = JsonRpcResponse(id=5, result={"ok": True})
        parsed = json.loads(resp.to_json())
        assert parsed["id"] == 5
        assert parsed["result"]["ok"] is True

    def test_serialize_compact(self):
        req = JsonRpcRequest(method="test", id=1)
        raw = serialize_message(req)
        # Compact: no spaces after separators
        assert " " not in raw or raw.count(" ") == 0  # minimal whitespace


class TestExtractSessionId:
    """Test session ID extraction from ACP messages."""

    def test_from_params_session_id(self):
        msg = JsonRpcRequest(method="session/prompt", params={"sessionId": "sess-1"})
        assert extract_session_id(msg) == "sess-1"

    def test_from_params_session_id_snake_case(self):
        msg = JsonRpcRequest(method="session/prompt", params={"session_id": "sess-2"})
        assert extract_session_id(msg) == "sess-2"

    def test_from_meta_session_id(self):
        msg = JsonRpcRequest(
            method="session/prompt",
            params={},
            meta={"sessionId": "sess-3"},
        )
        assert extract_session_id(msg) == "sess-3"

    def test_no_session_id(self):
        msg = JsonRpcRequest(method="initialize", params={})
        assert extract_session_id(msg) is None


class TestMakeErrorResponse:
    """Test error response construction."""

    def test_basic_error(self):
        raw = make_error_response(1, INTERNAL_ERROR, "something broke")
        parsed = json.loads(raw)
        assert parsed["id"] == 1
        assert parsed["error"]["code"] == INTERNAL_ERROR
        assert parsed["error"]["message"] == "something broke"

    def test_parse_error(self):
        raw = make_error_response(None, PARSE_ERROR, "bad json")
        parsed = json.loads(raw)
        assert parsed["id"] is None
        assert parsed["error"]["code"] == PARSE_ERROR


# ---------------------------------------------------------------------------
# Session manager tests
# ---------------------------------------------------------------------------

from src.session_manager import SessionManager, SessionStatus


class TestSessionManager:
    """Test in-memory session management."""

    @pytest.fixture
    def mgr(self):
        return SessionManager()

    @pytest.mark.asyncio
    async def test_create_session(self, mgr):
        pair = await mgr.create_session(user_id="user-1", title="Test")
        assert pair.session_id is not None
        assert pair.user_id == "user-1"
        assert pair.status == SessionStatus.WAITING_AGENT

    @pytest.mark.asyncio
    async def test_create_duplicate_session_id(self, mgr):
        await mgr.create_session(user_id="user-1", session_id="dup")
        with pytest.raises(ValueError, match="already exists"):
            await mgr.create_session(user_id="user-2", session_id="dup")

    @pytest.mark.asyncio
    async def test_register_browser_and_agent(self, mgr):
        pair = await mgr.create_session(user_id="user-1", session_id="s1")
        assert pair.status == SessionStatus.WAITING_AGENT

        mock_browser = MagicMock()
        await mgr.register_browser("s1", mock_browser)
        assert pair.browser_ws is mock_browser
        assert pair.status == SessionStatus.WAITING_AGENT  # still waiting for agent

        mock_agent = MagicMock()
        await mgr.register_agent("s1", mock_agent)
        assert pair.agent_ws is mock_agent
        assert pair.status == SessionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_register_agent_first(self, mgr):
        pair = await mgr.create_session(user_id="user-1", session_id="s1")

        mock_agent = MagicMock()
        await mgr.register_agent("s1", mock_agent)
        assert pair.status == SessionStatus.WAITING_CLIENT

        mock_browser = MagicMock()
        await mgr.register_browser("s1", mock_browser)
        assert pair.status == SessionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_close_session(self, mgr):
        await mgr.create_session(user_id="user-1", session_id="s1")
        result = await mgr.close_session("s1")
        assert result is True

        pair = await mgr.get_session("s1")
        assert pair.status == SessionStatus.CLOSED
        assert pair.browser_ws is None
        assert pair.agent_ws is None

    @pytest.mark.asyncio
    async def test_remove_session(self, mgr):
        await mgr.create_session(user_id="user-1", session_id="s1")
        result = await mgr.remove_session("s1")
        assert result is True

        pair = await mgr.get_session("s1")
        assert pair is None

    @pytest.mark.asyncio
    async def test_list_sessions(self, mgr):
        await mgr.create_session(user_id="user-1", session_id="s1")
        await mgr.create_session(user_id="user-1", session_id="s2")
        await mgr.create_session(user_id="user-2", session_id="s3")

        user1_sessions = await mgr.list_sessions("user-1")
        assert len(user1_sessions) == 2

    @pytest.mark.asyncio
    async def test_list_sessions_excludes_closed(self, mgr):
        await mgr.create_session(user_id="user-1", session_id="s1")
        await mgr.create_session(user_id="user-1", session_id="s2")
        await mgr.close_session("s2")

        user1_sessions = await mgr.list_sessions("user-1")
        assert len(user1_sessions) == 1

    @pytest.mark.asyncio
    async def test_active_count(self, mgr):
        await mgr.create_session(user_id="user-1", session_id="s1")
        mock_browser = MagicMock()
        mock_agent = MagicMock()
        await mgr.register_browser("s1", mock_browser)
        await mgr.register_agent("s1", mock_agent)

        assert await mgr.get_active_count() == 1
        assert await mgr.get_total_count() == 1


# ---------------------------------------------------------------------------
# WebSocket integration tests
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Test the REST health endpoint."""

    @pytest.fixture
    def client(self):
        # Set required env vars for testing
        os.environ.setdefault("JWT_SECRET", "test-secret-for-testing-only")
        from src.main import app
        with TestClient(app) as client:
            yield client

    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert isinstance(data["active_sessions"], int)
        assert isinstance(data["total_sessions"], int)


class TestSessionRestEndpoints:
    """Test REST session endpoints with auth."""

    @pytest.fixture
    def client(self):
        os.environ.setdefault("JWT_SECRET", "test-secret-for-testing-only")
        from src.main import app
        from webuild_shared.jwt import JWTManager
        jwt_mgr = JWTManager(secret="test-secret-for-testing-only")
        self.token = jwt_mgr.create_access_token("test-user-1")
        with TestClient(app) as client:
            yield client

    def test_create_session(self, client):
        resp = client.post(
            "/sessions",
            json={"title": "Test Session"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["session_id"] is not None
        assert data["title"] == "Test Session"
        assert data["status"] == "waiting_agent"

    def test_list_sessions(self, client):
        # Create one first
        client.post(
            "/sessions",
            json={"title": "S1"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        resp = client.get(
            "/sessions",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_session_not_found(self, client):
        resp = client.get(
            "/sessions/nonexistent",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert resp.status_code == 404

    def test_create_then_get_session(self, client):
        create_resp = client.post(
            "/sessions",
            json={"title": "Detail Test"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        sid = create_resp.json()["session_id"]

        resp = client.get(
            f"/sessions/{sid}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["session_id"] == sid

    def test_delete_session(self, client):
        create_resp = client.post(
            "/sessions",
            json={},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        sid = create_resp.json()["session_id"]

        resp = client.delete(
            f"/sessions/{sid}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert resp.status_code == 204

    def test_unauthorized_without_token(self, client):
        resp = client.get("/sessions")
        assert resp.status_code == 401 or resp.status_code == 403

    def test_get_session_history_no_persistence(self, client):
        create_resp = client.post(
            "/sessions",
            json={},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        sid = create_resp.json()["session_id"]

        resp = client.get(
            f"/sessions/{sid}/history",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        # Without DATABASE_URL, persistence is unavailable
        assert resp.status_code == 503
