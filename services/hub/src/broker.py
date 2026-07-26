"""Core broker logic for the Hub.

The Broker orchestrates WebSocket connections, performs the hello handshake,
manages the routing table, and forwards JSON-RPC messages between
ToolServer and ToolHarness clients.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import WebSocket

from connection import Connection
from routing_table import RoutingTable
from session import SessionManager
from wire.handshake import ClientKind, process_hello
from wire.protocol import (
    HELLO,
    SERVE,
    SESSION_BIND,
    TOOL_CALL,
    TOOL_CANCEL,
    TOOL_HOOK,
    TOOL_HOOK_REQUEST,
    deserialize,
    make_error,
    make_response,
    serialize,
    JsonRpcResponse,
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
)

log = structlog.get_logger(__name__)


class Broker:
    """Stateful broker that routes tool calls over WebSockets."""

    def __init__(self, max_concurrent_per_connection: int = 64) -> None:
        self.routing_table = RoutingTable()
        self.session_manager = SessionManager()
        self._max_concurrent = max_concurrent_per_connection
        # Maps connection_id -> Connection for quick lookup.
        self._connections: dict[str, Connection] = {}
        # Per-connection semaphores for admission control.
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        # Pending forwarded tool.call responses: broker_request_id -> asyncio.Future
        self._pending_responses: dict[str, asyncio.Future[Any]] = {}
        # Maps broker-forwarded-request-id -> (harness_connection_id, original_harness_request_id)
        self._forwarded_calls: dict[str, tuple[str, int | str]] = {}

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def handle_connection(self, ws: WebSocket) -> None:
        """Entry point for a new WebSocket client."""
        await ws.accept()
        conn = Connection(ws=ws)
        self._connections[conn.connection_id] = conn
        sem = asyncio.Semaphore(self._max_concurrent)
        self._semaphores[conn.connection_id] = sem

        log.info("ws_accepted", connection_id=conn.connection_id)

        try:
            # Phase 1: Handshake -- the first message must be a hello.
            if not await self._do_handshake(conn):
                return

            # Register in routing table and session manager.
            self.routing_table.register_connection(conn)

            # Phase 2: Main message loop.
            await self._message_loop(conn)
        except Exception:
            log.exception("connection_error", connection_id=conn.connection_id)
        finally:
            await self._cleanup(conn)

    async def _do_handshake(self, conn: Connection) -> bool:
        """Wait for the client's hello, validate it, send our response."""
        try:
            raw = await asyncio.wait_for(conn.ws.receive_text(), timeout=30.0)
        except (asyncio.TimeoutError, Exception):
            log.warning("handshake_timeout", connection_id=conn.connection_id)
            await conn.ws.close(code=4000, reason="Handshake timeout")
            return False

        try:
            data = deserialize(raw)
        except ValueError as exc:
            log.warning("handshake_bad_json", connection_id=conn.connection_id, error=str(exc))
            await conn.ws.close(code=4001, reason="Invalid JSON-RPC")
            return False

        if data.get("method") != HELLO:
            log.warning("handshake_not_hello", connection_id=conn.connection_id, method=data.get("method"))
            await conn.ws.close(code=4002, reason="First message must be hello")
            return False

        hs_result, response_json = process_hello(data.get("params", {}), data.get("id"))
        await conn.send_json(response_json)

        if hs_result is None:
            await conn.ws.close(code=4003, reason="Handshake validation failed")
            return False

        conn.kind = hs_result.kind
        conn.server_id = hs_result.server_id
        log.info(
            "handshake_complete",
            connection_id=conn.connection_id,
            kind=conn.kind.value,
            server_id=conn.server_id,
        )
        return True

    # ------------------------------------------------------------------
    # Main message loop
    # ------------------------------------------------------------------

    async def _message_loop(self, conn: Connection) -> None:
        """Process messages from a single connection until it disconnects."""
        while True:
            try:
                raw = await conn.ws.receive_text()
            except Exception:
                break

            try:
                data = deserialize(raw)
            except ValueError as exc:
                await conn.send_json(make_error(None, -32700, str(exc)))
                continue

            # Determine if this is a response to a forwarded request.
            if "result" in data or "error" in data:
                await self._handle_response(conn, data)
                continue

            method = data.get("method", "")
            request_id = data.get("id")
            params = data.get("params", {})

            handler = self._method_dispatch.get(method)
            if handler is None:
                await conn.send_json(make_error(request_id, METHOD_NOT_FOUND, f"Unknown method: {method}"))
                continue

            try:
                await handler(self, conn, request_id, params)
            except Exception:
                log.exception("method_error", method=method, connection_id=conn.connection_id)
                await conn.send_json(make_error(request_id, INTERNAL_ERROR, "Internal broker error"))

    _method_dispatch: dict[str, Any] = {
        SERVE: "_handle_serve",
        SESSION_BIND: "_handle_session_bind",
        TOOL_CALL: "_handle_tool_call",
        TOOL_CANCEL: "_handle_tool_cancel",
        TOOL_HOOK: "_handle_tool_hook",
        TOOL_HOOK_REQUEST: "_handle_tool_hook_request",
    }

    # Make the dispatch dict resolve to bound method references at class
    # definition time by replacing string names with actual methods below.
    # (We use strings here to avoid forward-reference issues; the broker
    # resolves them at call time via getattr.)

    # ------------------------------------------------------------------
    # Override dispatch to use getattr for late-binding
    # ------------------------------------------------------------------

    # (The _message_loop already calls handler(self, ...) via the dict of
    # string -> method name.  We replace it below with actual methods.)

    # ------------------------------------------------------------------
    # Method handlers
    # ------------------------------------------------------------------

    async def _handle_serve(
        self, conn: Connection, request_id: int | str | None, params: dict[str, Any]
    ) -> None:
        """Handle a ``serve`` request from a ToolServer."""
        if conn.kind != ClientKind.TOOL_SERVER:
            await conn.send_json(make_error(request_id, -32000, "Only ToolServer can serve"))
            return

        session_id = params.get("sessionId", "")
        tools = params.get("tools", [])

        if not session_id:
            await conn.send_json(make_error(request_id, -32602, "Missing sessionId"))
            return

        count = self.routing_table.serve_tools(conn.connection_id, session_id, tools)
        tool_ids = [t.get("toolId", "") for t in tools if t.get("toolId")]
        self.session_manager.register_server(session_id, conn.connection_id, tool_ids)

        await conn.send_json(make_response(request_id, result={"registered": count}))

    async def _handle_session_bind(
        self, conn: Connection, request_id: int | str | None, params: dict[str, Any]
    ) -> None:
        """Handle a ``session.bind`` from a ToolServer."""
        if conn.kind != ClientKind.TOOL_SERVER:
            await conn.send_json(make_error(request_id, -32000, "Only ToolServer can bind sessions"))
            return

        session_id = params.get("sessionId", "")
        if not session_id:
            await conn.send_json(make_error(request_id, -32602, "Missing sessionId"))
            return

        count = self.routing_table.bind_session(conn.connection_id, session_id)
        await conn.send_json(make_response(request_id, result={"bound": count}))

    async def _handle_tool_call(
        self, conn: Connection, request_id: int | str | None, params: dict[str, Any]
    ) -> None:
        """Handle a ``tool.call`` from a ToolHarness.

        Looks up the target ToolServer, forwards the call, and awaits the
        response before replying to the harness.
        """
        if conn.kind != ClientKind.TOOL_HARNESS:
            await conn.send_json(make_error(request_id, -32000, "Only ToolHarness can call tools"))
            return

        session_id = params.get("sessionId", "")
        tool_id = params.get("toolId", "")

        if not session_id or not tool_id:
            await conn.send_json(make_error(request_id, -32602, "Missing sessionId or toolId"))
            return

        target = self.routing_table.route_tool_call(session_id, tool_id)
        if target is None:
            await conn.send_json(
                make_error(request_id, -32001, f"No ToolServer for session={session_id} tool={tool_id}")
            )
            return

        # Admission control.
        sem = self._semaphores.get(target.connection_id)
        if sem is None or sem.locked():
            await conn.send_json(
                make_error(request_id, -32002, "ToolServer at capacity; try again later")
            )
            return

        # Register the harness in the session.
        self.session_manager.register_harness(session_id, conn.connection_id)
        self.session_manager.record_call(session_id)

        # Build a forwarded request with a broker-generated id.
        from wire.protocol import JsonRpcRequest
        forwarded = JsonRpcRequest(method=TOOL_CALL, params=params)
        forwarded_id = forwarded.id  # type: ignore[assignment]

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending_responses[forwarded_id] = fut
        self._forwarded_calls[forwarded_id] = (conn.connection_id, request_id)  # type: ignore[arg-type]

        # Forward to the ToolServer.
        try:
            async with sem:
                await target.send_json(serialize(forwarded))

                # Wait for the ToolServer's response (with timeout).
                response_data = await asyncio.wait_for(fut, timeout=300.0)
        except asyncio.TimeoutError:
            await conn.send_json(
                make_error(request_id, -32003, f"Tool call timed out: {tool_id}")
            )
            self._pending_responses.pop(forwarded_id, None)
            self._forwarded_calls.pop(forwarded_id, None)
            return
        except Exception as exc:
            await conn.send_json(make_error(request_id, INTERNAL_ERROR, str(exc)))
            self._pending_responses.pop(forwarded_id, None)
            self._forwarded_calls.pop(forwarded_id, None)
            return
        finally:
            self._pending_responses.pop(forwarded_id, None)
            self._forwarded_calls.pop(forwarded_id, None)

        # Forward the ToolServer's response back to the harness.
        if "error" in response_data and response_data["error"]:
            await conn.send_json(make_error(request_id, -32004, response_data["error"].get("message", "tool error")))
        else:
            await conn.send_json(make_response(request_id, result=response_data.get("result")))

    async def _handle_tool_cancel(
        self, conn: Connection, request_id: int | str | None, params: dict[str, Any]
    ) -> None:
        """Handle ``tool.cancel`` from a ToolHarness."""
        session_id = params.get("sessionId", "")
        tool_call_id = params.get("toolCallId", "")

        if session_id:
            self.session_manager.record_cancel(session_id)

        # Forward the cancel to all ToolServers in the session.
        # (Simplified: broadcast to servers registered for the session.)
        sess = self.session_manager.get(session_id) if session_id else None
        if sess:
            for server_conn_id in sess.server_connections:
                server_conn = self._connections.get(server_conn_id)
                if server_conn:
                    from wire.protocol import JsonRpcRequest
                    fwd = JsonRpcRequest(method=TOOL_CANCEL, params=params)
                    await server_conn.send_json(serialize(fwd))

        await conn.send_json(make_response(request_id, result={"cancelled": True, "toolCallId": tool_call_id}))

    async def _handle_tool_hook(
        self, conn: Connection, request_id: int | str | None, params: dict[str, Any]
    ) -> None:
        """Handle ``tool.hook`` (e.g. permission grant from harness to server)."""
        session_id = params.get("sessionId", "")
        target = self.routing_table.route_tool_call(session_id, params.get("toolId", ""))
        if target:
            from wire.protocol import JsonRpcRequest
            fwd = JsonRpcRequest(method=TOOL_HOOK, params=params)
            await target.send_json(serialize(fwd))
            await conn.send_json(make_response(request_id, result={"forwarded": True}))
        else:
            await conn.send_json(make_error(request_id, -32001, "No route for hook"))

    async def _handle_tool_hook_request(
        self, conn: Connection, request_id: int | str | None, params: dict[str, Any]
    ) -> None:
        """Handle ``tool.hook_request`` (e.g. permission request from server to harness)."""
        session_id = params.get("sessionId", "")
        # Route to all harnesses in the session.
        sess = self.session_manager.get(session_id) if session_id else None
        if sess and sess.harness_connections:
            from wire.protocol import JsonRpcRequest
            fwd = JsonRpcRequest(method=TOOL_HOOK_REQUEST, params=params)
            msg = serialize(fwd)
            for h_conn_id in sess.harness_connections:
                h_conn = self._connections.get(h_conn_id)
                if h_conn:
                    await h_conn.send_json(msg)
            await conn.send_json(make_response(request_id, result={"forwarded": True}))
        else:
            await conn.send_json(make_error(request_id, -32001, "No harness for hook_request"))

    # ------------------------------------------------------------------
    # Response handling (for forwarded tool.call)
    # ------------------------------------------------------------------

    async def _handle_response(self, conn: Connection, data: dict[str, Any]) -> None:
        """Handle a JSON-RPC response from a ToolServer (result of a forwarded call)."""
        resp_id = data.get("id")
        fut = self._pending_responses.get(resp_id)  # type: ignore[arg-type]
        if fut and not fut.done():
            fut.set_result(data)
        else:
            log.debug("unmatched_response", connection_id=conn.connection_id, id=resp_id)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def _cleanup(self, conn: Connection) -> None:
        """Remove all state associated with a disconnected connection."""
        self.routing_table.unregister_connection(conn.connection_id)
        affected_sessions = self.session_manager.remove_connection(conn.connection_id)
        self._connections.pop(conn.connection_id, None)
        self._semaphores.pop(conn.connection_id, None)

        # Cancel any pending futures that were waiting on this connection.
        for fwd_id, (harness_conn_id, _) in list(self._forwarded_calls.items()):
            if harness_conn_id == conn.connection_id:
                fut = self._pending_responses.pop(fwd_id, None)
                if fut and not fut.done():
                    fut.cancel()
                self._forwarded_calls.pop(fwd_id, None)

        log.info(
            "connection_cleaned",
            connection_id=conn.connection_id,
            affected_sessions=affected_sessions,
        )

        try:
            await conn.ws.close()
        except Exception:
            pass


# Fix dispatch dict: replace string method names with actual bound methods.
# This runs once at class-body level.
Broker._method_dispatch = {
    SERVE: Broker._handle_serve,
    SESSION_BIND: Broker._handle_session_bind,
    TOOL_CALL: Broker._handle_tool_call,
    TOOL_CANCEL: Broker._handle_tool_cancel,
    TOOL_HOOK: Broker._handle_tool_hook,
    TOOL_HOOK_REQUEST: Broker._handle_tool_hook_request,
}
