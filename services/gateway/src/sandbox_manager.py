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

from src.k8s_client import K8sClient
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

ENVIRONMENT_TEMPLATES: dict[str, SandboxEnvironment] = {
    "default": SandboxEnvironment(
        id="default",
        name="WeBuild Sandbox (Default)",
        container_image="registry.cn-hangzhou.aliyuncs.com/alinux/python:3.11-slim",
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

        # Reject duplicate ids early
        async with self._session_factory() as session:
            existing = await session.execute(select(Sandbox).where(Sandbox.id == sandbox_id))
            if existing.scalar_one_or_none() is not None:
                raise ValueError(f"Sandbox already exists: {sandbox_id}")

        # DB record first (status=creating)
        async with self._session_factory() as session:
            sandbox = Sandbox(
                id=sandbox_id,
                user_id=uuid.UUID(user_id),
                environment_id=request.environment_id,
                status=SandboxStatus.creating.value,
                namespace="webuild-sandbox",
                created_at=now,
                expires_at=expires_at,
            )
            session.add(sandbox)
            await session.commit()

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
                    "RELAY_URL": os.environ.get("RELAY_URL", "ws://relay-server:8002/ws"),
                    "RELAY_TOKEN": os.environ.get("RELAY_INTERNAL_TOKEN", "internal-sandbox-agent"),
                },
                resources=env.resource_profile.model_dump(),
                ttl_seconds=env.max_ttl_seconds,
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
                namespace="webuild-sandbox",
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
