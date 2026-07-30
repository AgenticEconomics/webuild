"""WeBuild Gateway — FastAPI application managing sandbox lifecycle on ACS Serverless."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from urllib.parse import quote

import structlog
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, WebSocket, status
from fastapi.responses import PlainTextResponse, Response

from webuild_shared.auth_middleware import get_current_user
from webuild_shared.db import get_engine, get_session_factory
from webuild_shared.logging import setup_logging

from src.acp_proxy import ACPProxy
from src.k8s_client import K8sClient
from src.models import (
    CreateSandboxRequest,
    SandboxEnvironment,
    SandboxFileInfo,
    SandboxFileListResponse,
    SandboxListResponse,
    SandboxResponse,
    SandboxUploadResponse,
)
from src.pathutil import PathValidationError
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


async def _owned_sandbox(sandbox_id: str, user: dict) -> SandboxResponse:
    try:
        sandbox = await _manager().get_sandbox(sandbox_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    if sandbox.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your sandbox")
    return sandbox


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
    return await _owned_sandbox(sandbox_id, user)


@app.delete("/sandboxes/{sandbox_id}", response_model=SandboxResponse)
async def delete_sandbox(sandbox_id: str, user: dict = Depends(get_current_user)):
    """Terminate a sandbox."""
    await _owned_sandbox(sandbox_id, user)
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
    await _owned_sandbox(sandbox_id, user)
    logs = await _manager().get_sandbox_logs(sandbox_id, tail_lines)
    return PlainTextResponse(content=logs)


# ------------------------------------------------------------------
# Workspace files (Phase VII)
# ------------------------------------------------------------------


@app.post(
    "/sandboxes/{sandbox_id}/files",
    response_model=SandboxUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_sandbox_files(
    sandbox_id: str,
    files: list[UploadFile] = File(...),
    dest: str = Query(default="inbox"),
    user: dict = Depends(get_current_user),
):
    """Upload one or more files into /workspace/inbox (default)."""
    await _owned_sandbox(sandbox_id, user)
    payloads: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        payloads.append((f.filename or "upload.bin", data))
    try:
        uploaded = await _manager().upload_files(sandbox_id, payloads, dest=dest)
    except PathValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("upload_sandbox_files_error", sandbox_id=sandbox_id)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    return SandboxUploadResponse(uploaded=uploaded, dest=dest, count=len(uploaded))


@app.get("/sandboxes/{sandbox_id}/files", response_model=SandboxFileListResponse)
async def list_sandbox_files(
    sandbox_id: str,
    prefix: str = Query(default="outputs"),
    user: dict = Depends(get_current_user),
):
    """List files under a workspace prefix (default: outputs)."""
    await _owned_sandbox(sandbox_id, user)
    try:
        rows = await _manager().list_files(sandbox_id, prefix=prefix)
    except PathValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("list_sandbox_files_error", sandbox_id=sandbox_id)
        raise HTTPException(status_code=500, detail=f"List failed: {e}")
    files = [SandboxFileInfo(**r) for r in rows]
    return SandboxFileListResponse(files=files, prefix=prefix, total=len(files))


@app.get("/sandboxes/{sandbox_id}/files/content")
async def download_sandbox_file(
    sandbox_id: str,
    path: str = Query(..., min_length=1),
    user: dict = Depends(get_current_user),
):
    """Download a single file from outputs/ or inbox/."""
    await _owned_sandbox(sandbox_id, user)
    try:
        name, data = await _manager().download_file(sandbox_id, path)
    except PathValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("download_sandbox_file_error", sandbox_id=sandbox_id, path=path)
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")

    disposition = f"attachment; filename*=UTF-8''{quote(name)}"
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


# ------------------------------------------------------------------
# WebSocket endpoint
# ------------------------------------------------------------------


@app.websocket("/ws/sandbox/{sandbox_id}")
async def websocket_proxy(ws: WebSocket, sandbox_id: str):
    """Proxy browser WebSocket to sandbox pod's ACP WebSocket."""
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

    try:
        sandbox = await _manager().get_sandbox(sandbox_id)
    except ValueError:
        await ws.close(code=4004, reason="Sandbox not found")
        return

    if sandbox.user_id != user_id:
        await ws.close(code=4003, reason="Not your sandbox")
        return

    await _proxy().proxy(ws, sandbox_id)
