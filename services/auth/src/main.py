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

    # Run Alembic migrations if alembic.ini / env present
    try:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.attributes["connection"] = engine
        command.upgrade(alembic_cfg, "head")
        log.info("auth_service.migrations_complete")
    except FileNotFoundError:
        log.warning("auth_service.no_alembic_ini", detail="Skipping migrations")
    except Exception as exc:
        log.error("auth_service.migration_failed", error=str(exc))

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
    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(users.router, prefix="/users", tags=["users"])
    app.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])

    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok", "service": "auth"}

    return app


app = create_app()
