"""Tests for the WeBuild Auth Service.

Uses an in-memory SQLite database (via aiosqlite) for isolated testing.
Run with: pytest tests/ -v
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import bcrypt
from webuild_shared.db import Base
from webuild_shared.jwt import JWTManager
from webuild_shared.models import ApiKey, User

# Set test env vars before importing app
os.environ["JWT_SECRET"] = "test-secret-key-for-unit-tests"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_ALGORITHM"] = "HS256"

from src.main import create_app


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def jwt_manager():
    return JWTManager(secret="test-secret-key-for-unit-tests")


@pytest_asyncio.fixture
async def test_password():
    return "secure-password-123"


@pytest_asyncio.fixture
async def test_user(session_factory, test_password):
    """Create a test user in the database."""
    async with session_factory() as session:
        password_hash = bcrypt.hashpw(test_password.encode(), bcrypt.gensalt()).decode()
        user = User(
            username="testuser",
            email="test@example.com",
            password_hash=password_hash,
            role="developer",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def admin_user(session_factory):
    """Create an admin user in the database."""
    async with session_factory() as session:
        password_hash = bcrypt.hashpw(b"admin-pass", bcrypt.gensalt()).decode()
        user = User(
            username="admin",
            email="admin@example.com",
            password_hash=password_hash,
            role="admin",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def access_token(jwt_manager, test_user):
    """Generate a valid access token for the test user."""
    return jwt_manager.create_access_token(
        user_id=str(test_user.id), scopes=["developer"]
    )


@pytest_asyncio.fixture
async def admin_token(jwt_manager, admin_user):
    """Generate a valid access token for the admin user."""
    return jwt_manager.create_access_token(
        user_id=str(admin_user.id), scopes=["admin"]
    )


@pytest_asyncio.fixture
async def app(engine, session_factory):
    """Create a FastAPI test app with overridden dependencies."""
    from fastapi import Depends

    from webuild_shared.auth_middleware import get_jwt_manager
    from webuild_shared.db import get_async_session

    application = create_app()

    # Override DB session dependency
    async def override_get_session():
        async with session_factory() as session:
            yield session

    # Override JWT manager dependency
    def override_jwt():
        return JWTManager(secret="test-secret-key-for-unit-tests")

    application.dependency_overrides[get_async_session] = override_get_session
    application.dependency_overrides[get_jwt_manager] = override_jwt

    yield application

    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Login Tests ──────────────────────────────────────────────────────────────


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client, test_user, test_password):
        response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": test_password},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, test_user):
        response = await client.post(
            "/auth/login",
            json={"username": "testuser", "password": "wrong-password"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_unknown_user(self, client):
        response = await client.post(
            "/auth/login",
            json={"username": "nonexistent", "password": "anything"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_missing_fields(self, client):
        response = await client.post("/auth/login", json={"username": "testuser"})
        assert response.status_code == 422


# ── Token Refresh Tests ──────────────────────────────────────────────────────


class TestTokenRefresh:
    @pytest.mark.asyncio
    async def test_refresh_success(self, client, jwt_manager, test_user):
        refresh_token = jwt_manager.create_refresh_token(user_id=str(test_user.id))
        response = await client.post(
            "/auth/token/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_fails(self, client, access_token):
        """Using an access token as a refresh token should fail."""
        response = await client.post(
            "/auth/token/refresh",
            json={"refresh_token": access_token},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_invalid_token(self, client):
        response = await client.post(
            "/auth/token/refresh",
            json={"refresh_token": "not-a-real-token"},
        )
        assert response.status_code == 401


# ── Current User Tests ───────────────────────────────────────────────────────


class TestMe:
    @pytest.mark.asyncio
    async def test_me_success(self, client, access_token, test_user):
        response = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"
        assert data["role"] == "developer"

    @pytest.mark.asyncio
    async def test_me_no_token(self, client):
        response = await client.get("/auth/me")
        assert response.status_code == 403  # HTTPBearer returns 403 when no creds

    @pytest.mark.asyncio
    async def test_me_invalid_token(self, client):
        response = await client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401


# ── API Key Tests ────────────────────────────────────────────────────────────


class TestApiKeys:
    @pytest.mark.asyncio
    async def test_create_api_key(self, client, access_token):
        response = await client.post(
            "/api-keys",
            json={"name": "test-key", "scopes": ["agent.use"]},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "test-key"
        assert data["key"].startswith("wb-")
        assert len(data["key"]) > 10  # prefix + base64 of 32 bytes
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_api_key_no_auth(self, client):
        response = await client.post(
            "/api-keys",
            json={"name": "test-key"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_api_keys(self, client, access_token):
        # Create a key first
        await client.post(
            "/api-keys",
            json={"name": "key-1"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response = await client.get(
            "/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["key_prefix"].startswith("wb-")
        # Plaintext key should NOT be in the list response
        assert "key" not in data[0]

    @pytest.mark.asyncio
    async def test_delete_api_key(self, client, access_token):
        # Create a key
        create_resp = await client.post(
            "/api-keys",
            json={"name": "to-delete"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        key_id = create_resp.json()["id"]

        # Delete it
        delete_resp = await client.delete(
            f"/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert delete_resp.status_code == 204

        # Verify it's gone
        list_resp = await client.get(
            "/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        key_ids = [k["id"] for k in list_resp.json()]
        assert key_id not in key_ids


# ── User Management Tests ────────────────────────────────────────────────────


class TestUsers:
    @pytest.mark.asyncio
    async def test_create_user_admin(self, client, admin_token):
        response = await client.post(
            "/users",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "new-password-123",
                "role": "developer",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newuser"
        assert data["role"] == "developer"

    @pytest.mark.asyncio
    async def test_create_user_non_admin_forbidden(self, client, access_token):
        response = await client.post(
            "/users",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "new-password-123",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_users_admin(self, client, admin_token):
        response = await client.get(
            "/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_get_user_self(self, client, access_token, test_user):
        response = await client.get(
            f"/users/{test_user.id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        assert response.json()["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_update_user_self(self, client, access_token, test_user):
        response = await client.put(
            f"/users/{test_user.id}",
            json={"email": "updated@example.com"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        assert response.json()["email"] == "updated@example.com"
