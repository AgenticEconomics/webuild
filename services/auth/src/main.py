"""WeBuild Auth Service — FastAPI application entry point."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from webuild_shared.db import get_engine, get_session_factory
from webuild_shared.logging import setup_logging

from src.invite import get_invite_email, seed_invite_whitelist
from src.routes import api_keys, auth, users

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create engine, run migrations; shutdown: dispose engine."""
    setup_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        json_output=os.environ.get("LOG_JSON", "false").lower() == "true",
    )
    log.info("auth_service.starting")

    # Create engine and attach to app state
    engine = get_engine()
    app.state.engine = engine

    # Create tables directly (simpler than Alembic for initial deployment)
    try:
        from webuild_shared.models import Base  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("auth_service.tables_created")
    except Exception as exc:
        log.error("auth_service.table_creation_failed", error=str(exc))

    # Seed invite-only whitelist accounts (idempotent)
    try:
        factory = get_session_factory(engine)
        summary = await seed_invite_whitelist(factory)
        app.state.invite_info = {
            "mode": "invite_only",
            "invite_email": summary.get("invite_email") or get_invite_email(),
            "whitelist_size": summary.get("total", 0),
        }
    except Exception as exc:
        log.error("auth_service.invite_seed_failed", error=str(exc))
        app.state.invite_info = {
            "mode": "invite_only",
            "invite_email": get_invite_email(),
            "whitelist_size": 0,
        }

    yield

    await engine.dispose()
    log.info("auth_service.stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="WeBuild Auth Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — allow configurable origins via env var
    allowed_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount routers
    # Routes mounted at root — Caddy strips /api/auth prefix via handle_path
    app.include_router(auth.router, tags=["auth"])
    app.include_router(users.router, prefix="/users", tags=["users"])
    app.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])

    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok", "service": "auth"}

    @app.get("/invite-info", tags=["auth"])
    async def invite_info():
        """Public invite-only notice (no credentials)."""
        info = getattr(app.state, "invite_info", None) or {
            "mode": "invite_only",
            "invite_email": get_invite_email(),
            "whitelist_size": 0,
        }
        return {
            **info,
            "message": (
                "WeBuild is invite-only. Email the invite address to request access; "
                "an administrator will send you a username and password."
            ),
        }

    return app


app = create_app()
