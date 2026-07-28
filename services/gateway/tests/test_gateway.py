"""Tests for WeBuild Gateway — sandbox lifecycle, K8s mocking, WebSocket proxy."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_USER_ID = str(uuid.uuid4())
FAKE_SANDBOX_ID = "abc123def4567890"


@pytest.fixture
def mock_k8s():
    """Return a fully-mocked K8sClient."""
    k8s = MagicMock()
    k8s.create_sandbox_pod.return_value = (
        f"sandbox-{FAKE_SANDBOX_ID}",
        f"sandbox-{FAKE_SANDBOX_ID}",
    )
    k8s.delete_sandbox_pod.return_value = None
    k8s.get_pod_status.return_value = "Running"
    k8s.get_pod_ip.return_value = "10.0.0.42"
    k8s.get_pod_logs.return_value = "2025-01-01T00:00:00Z sandbox started\n"
    k8s.list_sandbox_pods.return_value = []
    return k8s


@pytest.fixture
def mock_db_session():
    """Return a mock async session factory that tracks operations."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.add = MagicMock()
    session.commit = AsyncMock()

    # For select queries
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    factory = MagicMock(return_value=session)
    return factory, session, mock_result


@pytest.fixture
def sandbox_manager(mock_k8s, mock_db_session):
    factory, session, mock_result = mock_db_session
    from src.sandbox_manager import SandboxManager
    return SandboxManager(mock_k8s, factory)


# ---------------------------------------------------------------------------
# Unit tests: K8sClient
# ---------------------------------------------------------------------------


class TestK8sClient:
    def test_create_sandbox_pod_builds_correct_spec(self):
        from src.k8s_client import K8sClient

        k8s = K8sClient()
        mock_api = MagicMock()
        k8s._core_v1 = mock_api
        k8s._loaded = True

        pod_name, svc_name = k8s.create_sandbox_pod(
            sandbox_id="test123",
            image="test-image:latest",
            env_vars={"FOO": "bar"},
            ttl_seconds=1800,
        )

        assert pod_name == "sandbox-test123"
        assert svc_name == "sandbox-test123"

        # Verify pod was created with correct namespace
        call_args = mock_api.create_namespaced_pod.call_args
        assert call_args.kwargs["namespace"] == "webuild-sandbox"
        pod_body = call_args.kwargs["body"]
        assert pod_body.metadata.labels["webuild.io/sandbox"] == "test123"
        assert pod_body.metadata.labels["webuild.io/agent-mode"] == "webuild"

        container = pod_body.spec.containers[0]
        assert container.image == "test-image:latest"
        assert container.command is None  # image ENTRYPOINT
        assert container.args is None
        assert container.resources.requests["cpu"] == "1"
        assert container.resources.requests["memory"] == "2Gi"
        assert container.resources.limits["cpu"] == "4"
        assert container.resources.limits["memory"] == "8Gi"
        assert container.security_context.run_as_user == 1000
        assert container.security_context.capabilities.drop == ["ALL"]

        # Verify service was created
        svc_call = mock_api.create_namespaced_service.call_args
        assert svc_call.kwargs["namespace"] == "webuild-sandbox"

    def test_delete_sandbox_pod_handles_404(self):
        from kubernetes.client.exceptions import ApiException

        from src.k8s_client import K8sClient

        k8s = K8sClient()
        mock_api = MagicMock()
        k8s._core_v1 = mock_api
        k8s._loaded = True

        mock_api.delete_namespaced_service.side_effect = ApiException(status=404)
        mock_api.delete_namespaced_pod.side_effect = ApiException(status=404)

        # Should not raise
        k8s.delete_sandbox_pod("nonexistent")

    def test_get_pod_status_returns_phase(self):
        from src.k8s_client import K8sClient

        k8s = K8sClient()
        mock_api = MagicMock()
        k8s._core_v1 = mock_api
        k8s._loaded = True

        mock_pod = MagicMock()
        mock_pod.status.phase = "Running"
        mock_api.read_namespaced_pod_status.return_value = mock_pod

        assert k8s.get_pod_status("test123") == "Running"

    def test_get_pod_status_returns_none_for_missing(self):
        from kubernetes.client.exceptions import ApiException

        from src.k8s_client import K8sClient

        k8s = K8sClient()
        mock_api = MagicMock()
        k8s._core_v1 = mock_api
        k8s._loaded = True

        mock_api.read_namespaced_pod_status.side_effect = ApiException(status=404)

        assert k8s.get_pod_status("missing") is None


# ---------------------------------------------------------------------------
# Unit tests: SandboxManager
# ---------------------------------------------------------------------------


class TestSandboxManager:
    @pytest.mark.asyncio
    async def test_create_sandbox_unknown_env(self, sandbox_manager, mock_db_session):
        from src.models import CreateSandboxRequest

        factory, session, mock_result = mock_db_session

        with pytest.raises(ValueError, match="Unknown environment"):
            await sandbox_manager.create_sandbox(
                FAKE_USER_ID,
                CreateSandboxRequest(environment_id="nonexistent"),
            )

    @pytest.mark.asyncio
    async def test_create_sandbox_success(self, sandbox_manager, mock_db_session, mock_k8s):
        from src.models import CreateSandboxRequest, SandboxStatus

        factory, session, mock_result = mock_db_session

        resp = await sandbox_manager.create_sandbox(
            FAKE_USER_ID,
            CreateSandboxRequest(environment_id="default"),
        )

        assert resp.status == SandboxStatus.running
        assert resp.environment_id == "default"
        assert resp.namespace == "webuild-sandbox"
        assert resp.pod_name is not None
        mock_k8s.create_sandbox_pod.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_sandboxes(self, sandbox_manager, mock_db_session):
        factory, session, mock_result = mock_db_session
        result = await sandbox_manager.list_sandboxes(FAKE_USER_ID)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Unit tests: Pydantic models
# ---------------------------------------------------------------------------


class TestModels:
    def test_sandbox_status_enum(self):
        from src.models import SandboxStatus
        assert SandboxStatus.creating.value == "creating"
        assert SandboxStatus.running.value == "running"
        assert SandboxStatus.terminated.value == "terminated"

    def test_create_sandbox_request_defaults(self):
        from src.models import CreateSandboxRequest
        req = CreateSandboxRequest()
        assert req.environment_id == "default"

    def test_sandbox_environment_defaults(self):
        from src.models import SandboxEnvironment
        env = SandboxEnvironment(
            id="test", name="Test", container_image="test:latest"
        )
        assert env.max_ttl_seconds == 3600
        assert env.resource_profile.cpu_request == "1"
        assert env.resource_profile.memory_limit == "8Gi"

    def test_sandbox_response_serialization(self):
        from src.models import SandboxResponse, SandboxStatus

        now = datetime.now(timezone.utc)
        resp = SandboxResponse(
            id="abc123",
            user_id=FAKE_USER_ID,
            environment_id="default",
            status=SandboxStatus.running,
            pod_name="sandbox-abc123",
            namespace="webuild-sandbox",
            created_at=now,
        )
        data = resp.model_dump()
        assert data["status"] == "running"
        assert data["id"] == "abc123"


# ---------------------------------------------------------------------------
# Integration-style: REST routes (with full mocking)
# ---------------------------------------------------------------------------


class TestRoutes:
    """Test FastAPI routes with mocked dependencies."""

    @pytest.fixture(autouse=True)
    def setup_mocks(self, mock_k8s, mock_db_session):
        factory, session, mock_result = mock_db_session

        self.mock_k8s = mock_k8s
        self.mock_factory = factory
        self.mock_session = session
        self.mock_result = mock_result

        import src.main as main_mod

        # Patch globals in main module
        main_mod.k8s_client = mock_k8s
        main_mod.sandbox_manager = MagicMock()
        main_mod.sandbox_manager.create_sandbox = AsyncMock()
        main_mod.sandbox_manager.list_sandboxes = AsyncMock(return_value=[])
        main_mod.sandbox_manager.get_sandbox = AsyncMock()
        main_mod.sandbox_manager.terminate_sandbox = AsyncMock()
        main_mod.sandbox_manager.get_sandbox_logs = AsyncMock(return_value="log line 1\nlog line 2\n")
        main_mod.acp_proxy = MagicMock()

        self.main_mod = main_mod

    def _auth_header(self):
        """Create a fake JWT for testing."""
        from webuild_shared.jwt import JWTManager
        import os

        os.environ.setdefault("JWT_SECRET", "test-secret-for-testing-only")
        jwt_mgr = JWTManager(secret="test-secret-for-testing-only")
        token = jwt_mgr.create_access_token(FAKE_USER_ID, scopes=["agent.use", "sandbox.manage"])
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.asyncio
    async def test_health(self):
        from src.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_list_environments(self):
        from src.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            resp = await client.get("/environments", headers=self._auth_header())
            assert resp.status_code == 200
            envs = resp.json()
            assert len(envs) >= 1
            assert envs[0]["id"] == "default"

    @pytest.mark.asyncio
    async def test_create_sandbox_route(self):
        from src.models import SandboxResponse, SandboxStatus

        now = datetime.now(timezone.utc)
        self.main_mod.sandbox_manager.create_sandbox.return_value = SandboxResponse(
            id=FAKE_SANDBOX_ID,
            user_id=FAKE_USER_ID,
            environment_id="default",
            status=SandboxStatus.running,
            pod_name=f"sandbox-{FAKE_SANDBOX_ID}",
            namespace="webuild-sandbox",
            created_at=now,
        )

        from src.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/sandboxes",
                json={"environment_id": "default"},
                headers=self._auth_header(),
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["id"] == FAKE_SANDBOX_ID
            assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_list_sandboxes_route(self):
        from src.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            resp = await client.get("/sandboxes", headers=self._auth_header())
            assert resp.status_code == 200
            data = resp.json()
            assert "sandboxes" in data
            assert "total" in data

    @pytest.mark.asyncio
    async def test_get_sandbox_not_found(self):
        self.main_mod.sandbox_manager.get_sandbox.side_effect = ValueError("not found")

        from src.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            resp = await client.get("/sandboxes/missing", headers=self._auth_header())
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_sandbox_route(self):
        from src.models import SandboxResponse, SandboxStatus

        now = datetime.now(timezone.utc)
        self.main_mod.sandbox_manager.get_sandbox.return_value = SandboxResponse(
            id=FAKE_SANDBOX_ID,
            user_id=FAKE_USER_ID,
            environment_id="default",
            status=SandboxStatus.running,
            pod_name=f"sandbox-{FAKE_SANDBOX_ID}",
            namespace="webuild-sandbox",
            created_at=now,
        )
        self.main_mod.sandbox_manager.terminate_sandbox.return_value = SandboxResponse(
            id=FAKE_SANDBOX_ID,
            user_id=FAKE_USER_ID,
            environment_id="default",
            status=SandboxStatus.terminated,
            pod_name=f"sandbox-{FAKE_SANDBOX_ID}",
            namespace="webuild-sandbox",
            created_at=now,
            terminated_at=now,
        )

        from src.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            resp = await client.delete(
                f"/sandboxes/{FAKE_SANDBOX_ID}",
                headers=self._auth_header(),
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "terminated"

    @pytest.mark.asyncio
    async def test_get_sandbox_logs_route(self):
        from src.models import SandboxResponse, SandboxStatus

        now = datetime.now(timezone.utc)
        self.main_mod.sandbox_manager.get_sandbox.return_value = SandboxResponse(
            id=FAKE_SANDBOX_ID,
            user_id=FAKE_USER_ID,
            environment_id="default",
            status=SandboxStatus.running,
            pod_name=f"sandbox-{FAKE_SANDBOX_ID}",
            namespace="webuild-sandbox",
            created_at=now,
        )

        from src.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                f"/sandboxes/{FAKE_SANDBOX_ID}/logs",
                headers=self._auth_header(),
            )
            assert resp.status_code == 200
            assert "log line 1" in resp.text

    @pytest.mark.asyncio
    async def test_unauthorized_access(self):
        from src.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            resp = await client.get("/sandboxes")
            assert resp.status_code == 403  # no bearer token


# ---------------------------------------------------------------------------
# WebSocket proxy test (unit-level, no real sockets)
# ---------------------------------------------------------------------------


class TestACPProxy:
    @pytest.mark.asyncio
    async def test_proxy_closes_on_missing_pod(self, mock_k8s):
        from src.acp_proxy import ACPProxy

        mock_k8s.get_pod_ip.return_value = None
        proxy = ACPProxy(mock_k8s)

        mock_ws = AsyncMock()
        await proxy.proxy(mock_ws, "missing-sandbox")

        mock_ws.accept.assert_called_once()
        mock_ws.close.assert_called_once_with(code=4004, reason="Sandbox pod not found or not running")
