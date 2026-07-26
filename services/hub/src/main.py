"""WeBuild Hub Broker -- FastAPI application entry point.

Exposes:
  - ``GET /ws``     -- WebSocket endpoint for ToolServer / ToolHarness clients
  - ``GET /health`` -- Liveness / readiness probe
  - ``GET /stats``  -- Broker statistics (connections, sessions, routing)
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

# Ensure src/ is on sys.path so intra-package imports work when running
# ``uvicorn main:app`` from the src/ directory.
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from broker import Broker
from webuild_shared.logging import setup_logging

setup_logging()

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

_broker = Broker(
    max_concurrent_per_connection=int(os.environ.get("HUB_MAX_CONCURRENT", "64")),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("hub_broker_startup", port=os.environ.get("PORT", "8003"))
    yield
    log.info("hub_broker_shutdown")


app = FastAPI(
    title="WeBuild Hub Broker",
    version="0.1.0",
    description="Routes tool calls between ToolServer and ToolHarness via JSON-RPC 2.0 over WebSocket",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Accept a WebSocket client and hand off to the Broker."""
    try:
        await _broker.handle_connection(ws)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws_unhandled")


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "hub-broker"}


@app.get("/stats")
async def stats() -> dict:
    return {
        "routing": _broker.routing_table.stats(),
        "sessions": _broker.session_manager.stats(),
    }
