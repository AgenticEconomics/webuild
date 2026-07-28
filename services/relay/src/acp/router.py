"""AcpRouter — bidirectional message routing between browser and agent WebSockets.

The router is responsible for:
  - Forwarding JSON-RPC messages between paired WebSocket connections
  - Tracking pending request/response IDs to correlate replies
  - Persisting message history via the SessionStore
  - Graceful handling of disconnections and timeouts
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from src.acp.protocol import (
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    extract_session_id,
    make_error_response,
    parse_message,
    serialize_message,
    INTERNAL_ERROR,
    PARSE_ERROR,
)
from src.persistence import SessionStore
from src.session_manager import SessionManager, SessionPair, SessionStatus

logger = structlog.get_logger()

# Maximum size for a single WebSocket text frame (10 MB)
MAX_FRAME_SIZE = 10 * 1024 * 1024


class AcpRouter:
    """Routes ACP JSON-RPC messages between browser and agent WebSockets.

    Each router instance is scoped to a single session pair and manages
    the bidirectional forwarding loop.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        session_store: SessionStore | None,
    ) -> None:
        self._sessions = session_manager
        self._store = session_store
        # Per-session sequence counter for persisted messages
        self._seq_counters: dict[str, int] = {}
        self._seq_lock = asyncio.Lock()

    async def _next_seq(self, session_id: str) -> int:
        async with self._seq_lock:
            self._seq_counters.setdefault(session_id, 0)
            self._seq_counters[session_id] += 1
            return self._seq_counters[session_id]

    async def _persist(
        self,
        session_id: str,
        direction: str,
        raw: str,
    ) -> None:
        """Best-effort persistence — never blocks forwarding."""
        if self._store is None:
            return
        try:
            seq = await self._next_seq(session_id)
            payload = json.loads(raw)
            method = payload.get("method")
            await self._store.append_message(
                session_id=session_id,
                seq=seq,
                direction=direction,
                method=method,
                payload=payload,
            )
        except Exception:
            logger.exception("persist.message_failed", session_id=session_id)

    async def forward_browser_to_agent(
        self,
        session_id: str,
        pair: SessionPair,
    ) -> None:
        """Read from browser WebSocket and forward to agent."""
        ws: WebSocket = pair.browser_ws
        assert ws is not None
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > MAX_FRAME_SIZE:
                    await ws.send_text(
                        make_error_response(None, PARSE_ERROR, "Frame too large")
                    )
                    continue

                # Persist before forwarding
                await self._persist(session_id, "client_to_agent", raw)

                async with pair.agent_lock:
                    if pair.agent_ws is not None:
                        await pair.agent_ws.send_text(raw)
                    else:
                        # Agent not connected — queue or error
                        logger.warning(
                            "router.agent_disconnected",
                            session_id=session_id,
                        )
                        req_id = None
                        try:
                            req_id = json.loads(raw).get("id")
                        except Exception:
                            pass
                        await ws.send_text(
                            make_error_response(
                                req_id,
                                INTERNAL_ERROR,
                                "Agent not connected",
                            )
                        )

                pair.touch()
        except WebSocketDisconnect:
            logger.info("router.browser_disconnected", session_id=session_id)
        except Exception as exc:
            logger.exception("router.browser_loop_error", session_id=session_id, error=str(exc))

    async def forward_agent_to_browser(
        self,
        session_id: str,
        pair: SessionPair,
    ) -> None:
        """Read from agent WebSocket and forward to browser."""
        ws: WebSocket = pair.agent_ws
        assert ws is not None
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > MAX_FRAME_SIZE:
                    continue

                # Persist before forwarding
                await self._persist(session_id, "agent_to_client", raw)

                async with pair.browser_lock:
                    if pair.browser_ws is not None:
                        await pair.browser_ws.send_text(raw)
                    else:
                        logger.warning(
                            "router.browser_disconnected",
                            session_id=session_id,
                        )

                pair.touch()
        except WebSocketDisconnect:
            logger.info("router.agent_disconnected", session_id=session_id)
        except Exception as exc:
            logger.exception("router.agent_loop_error", session_id=session_id, error=str(exc))

    async def run_session(self, session_id: str, pair: SessionPair) -> None:
        """Run both forwarding loops concurrently for a session pair.

        Returns when either side disconnects.
        Only one caller may own the routing loop; concurrent callers wait.
        """
        if pair.browser_ws is None or pair.agent_ws is None:
            logger.warning("router.incomplete_pair", session_id=session_id)
            return

        async with pair.routing_lock:
            if pair.is_routing:
                already = True
            else:
                pair.is_routing = True
                already = False

        if already:
            logger.info("router.already_running", session_id=session_id)
            while pair.is_routing:
                await asyncio.sleep(0.25)
            return

        logger.info("router.session_started", session_id=session_id)

        # Update status
        pair.status = SessionStatus.ACTIVE
        if self._store:
            await self._store.update_status(session_id, "active")

        browser_task = asyncio.create_task(
            self.forward_browser_to_agent(session_id, pair)
        )
        agent_task = asyncio.create_task(
            self.forward_agent_to_browser(session_id, pair)
        )

        try:
            # Wait for either side to disconnect
            done, pending = await asyncio.wait(
                [browser_task, agent_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel the other loop
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        finally:
            pair.is_routing = False
            # Clean up
            pair.status = SessionStatus.CLOSED
            pair.browser_ws = None
            pair.agent_ws = None
            if self._store:
                await self._store.close_session(session_id)

            logger.info("router.session_ended", session_id=session_id)

            # Clean up the sequence counter
            async with self._seq_lock:
                self._seq_counters.pop(session_id, None)
