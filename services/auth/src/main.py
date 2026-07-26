"""WeBuild Auth Service — FastAPI application entry point."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from webuild_shared.db import get_engine
from webuild_shared.logging import setup_logging

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

    return app


app = create_app()
