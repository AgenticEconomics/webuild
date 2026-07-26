"""WeBuild Gateway — FastAPI application managing sandbox lifecycle on ACS Serverless."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, status
from fastapi.responses import PlainTextResponse

from webuild_shared.auth_middleware import get_current_user
from webuild_shared.db import get_engine, get_session_factory
from webuild_shared.logging import setup_logging

from src.acp_proxy import ACPProxy
from src.k8s_client import K8sClient
from src.models import (
    CreateSandboxRequest,
    SandboxEnvironment,
    SandboxListResponse,
    SandboxResponse,
)
from src.sandbox_manager import ENVIRONMENT_TEMPLATES, SandboxManager

logger = structlog.get_logger()

# ------------------------------------------------------------------
# Global singletons (initialised in lifespan)
# ------------------------------------------------------------------
k8s_client: K8sClient | None = None
sandbox_manager: SandboxManager | None = None
acp_proxy: ACPProxy | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle: K8s config, DB engine, background TTL task."""
    global k8s_client, sandbox_manager, acp_proxy

    setup_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        json_output=os.environ.get("LOG_JSON", "false").lower() == "true",
    )

    # Kubernetes
    k8s_client = K8sClient()
    kubeconfig_path = os.environ.get("KUBECONFIG", "/run/secrets/sandbox-kubeconfig")
    if os.path.exists(kubeconfig_path):
        k8s_client.load_config(kubeconfig_path)
    else:
        k8s_client.load_config()  # fallback to default
    logger.info("k8s_client_ready")

    # Database
    engine = get_engine()
    session_factory = get_session_factory(engine)
    logger.info("db_engine_ready")

    # Manager + proxy
    sandbox_manager = SandboxManager(k8s_client, session_factory)
    acp_proxy = ACPProxy(k8s_client)

    # Background TTL enforcement
    import asyncio

    ttl_task = asyncio.create_task(sandbox_manager.ttl_enforcement_loop(interval_seconds=60))
    logger.info("gateway_started")

    yield

    # Shutdown
    ttl_task.cancel()
    try:
        await ttl_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()
    logger.info("gateway_stopped")


app = FastAPI(
    title="WeBuild Gateway",
    version="0.1.0",
    lifespan=lifespan,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _manager() -> SandboxManager:
    if sandbox_manager is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")
    return sandbox_manager


def _proxy() -> ACPProxy:
    if acp_proxy is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")
    return acp_proxy


# ------------------------------------------------------------------
# REST routes
# ------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway"}


@app.get("/environments", response_model=list[SandboxEnvironment])
async def list_environments(user: dict = Depends(get_current_user)):
    """List available sandbox environment templates."""
    return list(ENVIRONMENT_TEMPLATES.values())


@app.post("/sandboxes", response_model=SandboxResponse, status_code=status.HTTP_201_CREATED)
async def create_sandbox(
    request: CreateSandboxRequest,
    user: dict = Depends(get_current_user),
):
    """Create a new sandbox (provisions K8s pod)."""
    try:
        return await _manager().create_sandbox(user["user_id"], request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("create_sandbox_error", user_id=user["user_id"])
        raise HTTPException(status_code=500, detail=f"Failed to create sandbox: {e}")


@app.get("/sandboxes", response_model=SandboxListResponse)
async def list_sandboxes(user: dict = Depends(get_current_user)):
    """List all sandboxes for the authenticated user."""
    sandboxes = await _manager().list_sandboxes(user["user_id"])
    return SandboxListResponse(sandboxes=sandboxes, total=len(sandboxes))


@app.get("/sandboxes/{sandbox_id}", response_model=SandboxResponse)
async def get_sandbox(sandbox_id: str, user: dict = Depends(get_current_user)):
    """Get sandbox detail with live pod status."""
    try:
        sandbox = await _manager().get_sandbox(sandbox_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your sandbox")

    return sandbox


@app.delete("/sandboxes/{sandbox_id}", response_model=SandboxResponse)
async def delete_sandbox(sandbox_id: str, user: dict = Depends(get_current_user)):
    """Terminate a sandbox."""
    try:
        sandbox = await _manager().get_sandbox(sandbox_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your sandbox")

    try:
        return await _manager().terminate_sandbox(sandbox_id)
    except Exception as e:
        logger.exception("terminate_sandbox_error", sandbox_id=sandbox_id)
        raise HTTPException(status_code=500, detail=f"Failed to terminate sandbox: {e}")


@app.get("/sandboxes/{sandbox_id}/logs", response_class=PlainTextResponse)
async def get_sandbox_logs(
    sandbox_id: str,
    tail_lines: int = Query(default=200, ge=1, le=10000),
    user: dict = Depends(get_current_user),
):
    """Get pod logs from a sandbox."""
    try:
        sandbox = await _manager().get_sandbox(sandbox_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your sandbox")

    logs = await _manager().get_sandbox_logs(sandbox_id, tail_lines)
    return PlainTextResponse(content=logs)


# ------------------------------------------------------------------
# WebSocket endpoint
# ------------------------------------------------------------------


@app.websocket("/ws/sandbox/{sandbox_id}")
async def websocket_proxy(ws: WebSocket, sandbox_id: str):
    """Proxy browser WebSocket to sandbox pod's ACP WebSocket."""
    # Auth: extract token from query param (WS can't use Authorization header reliably)
    from webuild_shared.jwt import JWTManager

    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001, reason="Missing token query parameter")
        return

    try:
        jwt_mgr = JWTManager()
        payload = jwt_mgr.verify_token(token, expected_type="access")
        user_id = payload.sub
    except Exception:
        await ws.close(code=4001, reason="Invalid or expired token")
        return

    # Verify ownership
    try:
        sandbox = await _manager().get_sandbox(sandbox_id)
    except ValueError:
        await ws.close(code=4004, reason="Sandbox not found")
        return

    if sandbox.user_id != user_id:
        await ws.close(code=4003, reason="Not your sandbox")
        return

    await _proxy().proxy(ws, sandbox_id)
