"""Sandbox lifecycle manager — bridges K8s operations with DB state."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from webuild_shared.models import Sandbox

from src.k8s_client import K8sClient, SANDBOX_NAMESPACE
from src.models import (
    CreateSandboxRequest,
    ResourceProfile,
    SandboxEnvironment,
    SandboxResponse,
    SandboxStatus,
)

logger = structlog.get_logger()

# ------------------------------------------------------------------
# Environment templates (static for now; could move to DB later)
# ------------------------------------------------------------------

# Phase V: full webuild binary image (override via SANDBOX_IMAGE).
# Legacy Python chat-only kept as environment_id=legacy-python.
_DEFAULT_SANDBOX_IMAGE = os.environ.get(
    "SANDBOX_IMAGE",
    "xingu-aliyun-acr-registry.cn-hangzhou.cr.aliyuncs.com/webuild/sandbox:latest",
)
_LEGACY_PYTHON_IMAGE = os.environ.get(
    "SANDBOX_LEGACY_IMAGE",
    "registry.cn-hangzhou.aliyuncs.com/alinux/python:3.11-slim",
)

def effective_resources(profile: ResourceProfile) -> dict:
    """Apply optional SANDBOX_* resource overrides (local k3s nodes are smaller)."""
    data = profile.model_dump()
    mapping = {
        "cpu_request": "SANDBOX_CPU_REQUEST",
        "memory_request": "SANDBOX_MEMORY_REQUEST",
        "cpu_limit": "SANDBOX_CPU_LIMIT",
        "memory_limit": "SANDBOX_MEMORY_LIMIT",
        "ephemeral_storage": "SANDBOX_EPHEMERAL_STORAGE",
    }
    for field, env_name in mapping.items():
        value = os.environ.get(env_name, "").strip()
        if value:
            data[field] = value
    return data


ENVIRONMENT_TEMPLATES: dict[str, SandboxEnvironment] = {
    "default": SandboxEnvironment(
        id="default",
        name="WeBuild Sandbox (Full Agent)",
        container_image=_DEFAULT_SANDBOX_IMAGE,
        resource_profile=ResourceProfile(
            cpu_request="1",
            memory_request="2Gi",
            cpu_limit="4",
            memory_limit="8Gi",
            ephemeral_storage="20Gi",
        ),
        max_ttl_seconds=3600,
    ),
    "legacy-python": SandboxEnvironment(
        id="legacy-python",
        name="WeBuild Sandbox (Legacy Python Chat)",
        container_image=_LEGACY_PYTHON_IMAGE,
        resource_profile=ResourceProfile(
            cpu_request="500m",
            memory_request="1Gi",
            cpu_limit="2",
            memory_limit="4Gi",
            ephemeral_storage="10Gi",
        ),
        max_ttl_seconds=3600,
    ),
}


class SandboxManager:
    """Manages sandbox creation, termination, listing, and TTL enforcement."""

    def __init__(self, k8s: K8sClient, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._k8s = k8s
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_sandbox(
        self, user_id: str, request: CreateSandboxRequest
    ) -> SandboxResponse:
        """Create a sandbox: provision K8s pod, persist to DB, return info."""

        env = ENVIRONMENT_TEMPLATES.get(request.environment_id)
        if env is None:
            raise ValueError(f"Unknown environment: {request.environment_id}")

        # Prefer caller-provided id so session_id == sandbox_id (agent joins the same session)
        if request.id:
            sandbox_id = request.id.strip()
            if not sandbox_id:
                raise ValueError("Sandbox id cannot be empty")
        else:
            sandbox_id = uuid.uuid4().hex[:16]
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=env.max_ttl_seconds)

        # Reject active duplicates; allow recreate when previously terminated
        # (e.g. ImagePullBackOff recovery after refreshing ACR pull secret).
        async with self._session_factory() as session:
            existing = await session.execute(select(Sandbox).where(Sandbox.id == sandbox_id))
            row = existing.scalar_one_or_none()
            if row is not None:
                if row.status != SandboxStatus.terminated.value:
                    raise ValueError(f"Sandbox already exists: {sandbox_id}")
                await session.execute(
                    update(Sandbox)
                    .where(Sandbox.id == sandbox_id)
                    .values(
                        user_id=uuid.UUID(user_id),
                        environment_id=request.environment_id,
                        status=SandboxStatus.creating.value,
                        pod_name=None,
                        namespace=SANDBOX_NAMESPACE,
                        created_at=now,
                        expires_at=expires_at,
                        terminated_at=None,
                    )
                )
                await session.commit()
            else:
                sandbox = Sandbox(
                    id=sandbox_id,
                    user_id=uuid.UUID(user_id),
                    environment_id=request.environment_id,
                    status=SandboxStatus.creating.value,
                    namespace=SANDBOX_NAMESPACE,
                    created_at=now,
                    expires_at=expires_at,
                )
                session.add(sandbox)
                await session.commit()

        # Ensure no stale pod/service leftovers before provisioning
        await asyncio.to_thread(self._k8s.delete_sandbox_pod, sandbox_id)

        # Provision pod (blocking K8s call — run in thread)
        try:
            pod_name, svc_name = await asyncio.to_thread(
                self._k8s.create_sandbox_pod,
                sandbox_id=sandbox_id,
                image=env.container_image,
                env_vars={
                    "SANDBOX_ID": sandbox_id,
                    "SESSION_ID": sandbox_id,
                    "WEBUILD_USER_ID": user_id,
                    "DASHSCOPE_API_KEY": os.environ.get("DASHSCOPE_API_KEY", ""),
                    "MODEL": os.environ.get("MODEL", "qwen-max"),
                    # ACS: wss://…:443. Local k3s: ws://<node-ip>/ws/relay (HTTP edge).
                    "RELAY_URL": os.environ.get(
                        "RELAY_URL", "wss://webuild.datoms.cn/ws/relay"
                    ),
                    "RELAY_TOKEN": os.environ.get(
                        "RELAY_INTERNAL_TOKEN", "internal-sandbox-agent"
                    ),
                    "WEBUILD_SANDBOX_MODE": "1",
                    "WEBUILD_YOLO": os.environ.get("WEBUILD_YOLO", "1"),
                    "WEBUILD_WORKSPACE": "/workspace",
                    # webuild = full agent (default image); python = ConfigMap legacy
                    "SANDBOX_AGENT": (
                        "python"
                        if request.environment_id == "legacy-python"
                        else os.environ.get("SANDBOX_AGENT", "webuild")
                    ),
                    "SANDBOX_REPO_URL": os.environ.get("SANDBOX_REPO_URL", ""),
                    "SANDBOX_REPO_BRANCH": os.environ.get("SANDBOX_REPO_BRANCH", "main"),
                    "HUB_WS_URL": os.environ.get(
                        "HUB_WS_URL", "wss://webuild.datoms.cn/ws/hub"
                    ),
                    "RUST_LOG": os.environ.get("SANDBOX_RUST_LOG", "info,xai_webuild_shell=debug"),
                    "WEBUILD_LOG": "1",
                },
                resources=effective_resources(env.resource_profile),
                ttl_seconds=env.max_ttl_seconds,
                agent_mode=(
                    "python"
                    if request.environment_id == "legacy-python"
                    else os.environ.get("SANDBOX_AGENT", "webuild")
                ),
            )

            async with self._session_factory() as session:
                await session.execute(
                    update(Sandbox)
                    .where(Sandbox.id == sandbox_id)
                    .values(pod_name=pod_name, status=SandboxStatus.running.value)
                )
                await session.commit()

            return SandboxResponse(
                id=sandbox_id,
                user_id=user_id,
                environment_id=request.environment_id,
                status=SandboxStatus.running,
                pod_name=pod_name,
                namespace=SANDBOX_NAMESPACE,
                created_at=now,
                expires_at=expires_at,
            )

        except Exception:
            logger.exception("sandbox_create_failed", sandbox_id=sandbox_id)
            async with self._session_factory() as session:
                await session.execute(
                    update(Sandbox)
                    .where(Sandbox.id == sandbox_id)
                    .values(status=SandboxStatus.terminated.value, terminated_at=datetime.now(timezone.utc))
                )
                await session.commit()
            raise

    async def terminate_sandbox(self, sandbox_id: str) -> SandboxResponse:
        """Terminate a sandbox: delete pod, update DB."""

        # Verify it exists
        async with self._session_factory() as session:
            result = await session.execute(select(Sandbox).where(Sandbox.id == sandbox_id))
            sandbox = result.scalar_one_or_none()
            if sandbox is None:
                raise ValueError(f"Sandbox not found: {sandbox_id}")

            # Delete K8s resources
            await asyncio.to_thread(self._k8s.delete_sandbox_pod, sandbox_id)

            now = datetime.now(timezone.utc)
            sandbox.status = SandboxStatus.terminated.value
            sandbox.terminated_at = now
            await session.commit()

            return SandboxResponse(
                id=sandbox.id,
                user_id=str(sandbox.user_id),
                environment_id=sandbox.environment_id,
                status=SandboxStatus.terminated,
                pod_name=sandbox.pod_name,
                namespace=sandbox.namespace,
                created_at=sandbox.created_at,
                expires_at=sandbox.expires_at,
                terminated_at=now,
            )

    async def list_sandboxes(self, user_id: str) -> list[SandboxResponse]:
        """List all sandboxes for a user (active and terminated)."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Sandbox)
                .where(Sandbox.user_id == uuid.UUID(user_id))
                .order_by(Sandbox.created_at.desc())
            )
            sandboxes = result.scalars().all()
            return [self._to_response(s) for s in sandboxes]

    async def get_sandbox(self, sandbox_id: str) -> SandboxResponse:
        """Get sandbox detail with live pod status."""
        async with self._session_factory() as session:
            result = await session.execute(select(Sandbox).where(Sandbox.id == sandbox_id))
            sandbox = result.scalar_one_or_none()
            if sandbox is None:
                raise ValueError(f"Sandbox not found: {sandbox_id}")

            # Fetch live pod phase
            pod_phase = None
            if sandbox.status != SandboxStatus.terminated.value:
                pod_phase = await asyncio.to_thread(self._k8s.get_pod_status, sandbox_id)
                # If pod is gone but DB says running, mark terminated
                if pod_phase is None and sandbox.status == SandboxStatus.running.value:
                    sandbox.status = SandboxStatus.terminated.value
                    sandbox.terminated_at = datetime.now(timezone.utc)
                    await session.commit()

            resp = self._to_response(sandbox)
            resp.pod_phase = pod_phase
            return resp

    # ------------------------------------------------------------------
    # Pod logs
    # ------------------------------------------------------------------

    async def get_sandbox_logs(self, sandbox_id: str, tail_lines: int = 200) -> str:
        """Get pod logs via K8s API."""
        return await asyncio.to_thread(self._k8s.get_pod_logs, sandbox_id, tail_lines)

    # ------------------------------------------------------------------
    # Workspace files (Phase VII)
    # ------------------------------------------------------------------

    MAX_UPLOAD_FILE_BYTES = 32 * 1024 * 1024
    MAX_UPLOAD_TOTAL_BYTES = 64 * 1024 * 1024
    MAX_UPLOAD_FILES = 20

    async def _require_running_pod(self, sandbox_id: str) -> SandboxResponse:
        sandbox = await self.get_sandbox(sandbox_id)
        if sandbox.status != SandboxStatus.running:
            raise ValueError(f"Sandbox is not running (status={sandbox.status.value})")
        phase = sandbox.pod_phase
        if phase and phase not in ("Running",):
            # Allow missing phase (race) but reject known bad phases
            if phase in ("Failed", "Succeeded", "Unknown"):
                raise ValueError(f"Sandbox pod not ready (phase={phase})")
        return sandbox

    async def upload_files(
        self,
        sandbox_id: str,
        files: list[tuple[str, bytes]],
        dest: str = "inbox",
    ) -> list[str]:
        """Upload files into /workspace/<dest>. Returns relative paths."""
        if not files:
            raise ValueError("No files provided")
        if len(files) > self.MAX_UPLOAD_FILES:
            raise ValueError(f"Too many files (max {self.MAX_UPLOAD_FILES})")
        total = sum(len(b) for _, b in files)
        if total > self.MAX_UPLOAD_TOTAL_BYTES:
            raise ValueError(f"Total upload too large (max {self.MAX_UPLOAD_TOTAL_BYTES} bytes)")
        for name, data in files:
            if len(data) > self.MAX_UPLOAD_FILE_BYTES:
                raise ValueError(
                    f"File {name!r} exceeds {self.MAX_UPLOAD_FILE_BYTES} byte limit"
                )

        await self._require_running_pod(sandbox_id)

        uploaded: list[str] = []
        for name, data in files:
            path = await asyncio.to_thread(
                self._k8s.upload_file_to_pod, sandbox_id, dest, name, data
            )
            uploaded.append(path)
            logger.info("sandbox.file_uploaded", sandbox_id=sandbox_id, path=path, size=len(data))
        return uploaded

    async def list_files(self, sandbox_id: str, prefix: str = "outputs") -> list[dict]:
        await self._require_running_pod(sandbox_id)
        return await asyncio.to_thread(self._k8s.list_files_in_pod, sandbox_id, prefix)

    async def download_file(self, sandbox_id: str, rel_path: str) -> tuple[str, bytes]:
        await self._require_running_pod(sandbox_id)
        return await asyncio.to_thread(self._k8s.download_file_from_pod, sandbox_id, rel_path)

    # ------------------------------------------------------------------
    # TTL enforcement background task
    # ------------------------------------------------------------------

    async def ttl_enforcement_loop(self, interval_seconds: int = 60) -> None:
        """Background task that terminates expired sandboxes every interval."""
        logger.info("ttl_enforcement_started", interval=interval_seconds)
        while True:
            try:
                await self._enforce_ttl()
            except Exception:
                logger.exception("ttl_enforcement_error")
            await asyncio.sleep(interval_seconds)

    async def _enforce_ttl(self) -> None:
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            result = await session.execute(
                select(Sandbox).where(
                    Sandbox.status.in_(
                        [SandboxStatus.creating.value, SandboxStatus.running.value]
                    ),
                    Sandbox.expires_at.isnot(None),
                    Sandbox.expires_at <= now,
                )
            )
            expired = result.scalars().all()

        for sandbox in expired:
            logger.info("ttl_expired", sandbox_id=sandbox.id, expires_at=str(sandbox.expires_at))
            try:
                await self.terminate_sandbox(sandbox.id)
            except Exception:
                logger.exception("ttl_terminate_error", sandbox_id=sandbox.id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_response(sandbox: Sandbox) -> SandboxResponse:
        return SandboxResponse(
            id=sandbox.id,
            user_id=str(sandbox.user_id),
            environment_id=sandbox.environment_id,
            status=SandboxStatus(sandbox.status),
            pod_name=sandbox.pod_name,
            namespace=sandbox.namespace,
            created_at=sandbox.created_at,
            expires_at=sandbox.expires_at,
            terminated_at=sandbox.terminated_at,
        )
