"""Session persistence layer — PostgreSQL storage for session metadata and message history.

Uses SQLAlchemy async models from webuild_shared.db as a base, and defines
relay-specific tables for relay_sessions and relay_messages.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, select, update, delete
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column, relationship

from webuild_shared.db import Base

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RelaySession(Base):
    """Persisted session metadata."""
    __tablename__ = "relay_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str | None] = mapped_column(String(256))
    model: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list["RelayMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="RelayMessage.seq",
    )

    __table_args__ = (
        Index("idx_relay_sessions_user", "user_id", "status"),
        Index("idx_relay_sessions_created", "created_at"),
    )


class RelayMessage(Base):
    """A single JSON-RPC message exchanged within a relay session.

    Messages are appended in order and stored as raw JSONB for full fidelity.
    """
    __tablename__ = "relay_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("relay_sessions.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # "client_to_agent" | "agent_to_client"
    method: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped["RelaySession"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("idx_relay_messages_session_seq", "session_id", "seq"),
    )


# ---------------------------------------------------------------------------
# Data-access helpers
# ---------------------------------------------------------------------------

class SessionStore:
    """Thin async wrapper around SQLAlchemy for relay persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def create_session(
        self,
        session_id: str,
        user_id: str,
        title: str | None = None,
        model: str | None = None,
    ) -> None:
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            logger.warning(
                "persist.session_skip_invalid_user",
                session_id=session_id,
                user_id=user_id,
            )
            return
        async with self._factory() as db:
            # Upsert-friendly: ignore if already exists
            existing = await db.execute(
                select(RelaySession).where(RelaySession.id == session_id)
            )
            if existing.scalar_one_or_none() is not None:
                await db.execute(
                    update(RelaySession)
                    .where(RelaySession.id == session_id)
                    .values(user_id=uid, status="created", updated_at=_utcnow(), closed_at=None)
                )
                await db.commit()
                logger.info("persist.session_reopened", session_id=session_id)
                return
            rec = RelaySession(
                id=session_id,
                user_id=uid,
                title=title,
                model=model,
                status="created",
            )
            db.add(rec)
            await db.commit()
            logger.info("persist.session_created", session_id=session_id)

    async def update_user(self, session_id: str, user_id: str) -> None:
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            return
        async with self._factory() as db:
            await db.execute(
                update(RelaySession)
                .where(RelaySession.id == session_id)
                .values(user_id=uid, updated_at=_utcnow())
            )
            await db.commit()

    async def update_title(self, session_id: str, title: str) -> None:
        async with self._factory() as db:
            await db.execute(
                update(RelaySession)
                .where(RelaySession.id == session_id)
                .values(title=title[:256], updated_at=_utcnow())
            )
            await db.commit()

    async def update_status(self, session_id: str, status: str) -> None:
        async with self._factory() as db:
            stmt = (
                update(RelaySession)
                .where(RelaySession.id == session_id)
                .values(status=status, updated_at=_utcnow())
            )
            await db.execute(stmt)
            await db.commit()

    async def close_session(self, session_id: str) -> None:
        async with self._factory() as db:
            now = _utcnow()
            stmt = (
                update(RelaySession)
                .where(RelaySession.id == session_id)
                .values(status="closed", updated_at=now, closed_at=now)
            )
            await db.execute(stmt)
            await db.commit()
            logger.info("persist.session_closed", session_id=session_id)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        async with self._factory() as db:
            result = await db.execute(
                select(RelaySession).where(RelaySession.id == session_id)
            )
            rec = result.scalar_one_or_none()
            if rec is None:
                return None
            return self._session_to_dict(rec)

    async def list_sessions(self, user_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        async with self._factory() as db:
            result = await db.execute(
                select(RelaySession)
                .where(RelaySession.user_id == uuid.UUID(user_id))
                .order_by(RelaySession.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return [self._session_to_dict(r) for r in result.scalars().all()]

    async def append_message(
        self,
        session_id: str,
        seq: int,
        direction: str,
        method: str | None,
        payload: dict[str, Any],
    ) -> None:
        async with self._factory() as db:
            msg = RelayMessage(
                session_id=session_id,
                seq=seq,
                direction=direction,
                method=method,
                payload=payload,
            )
            db.add(msg)
            await db.commit()

    async def get_messages(
        self,
        session_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        async with self._factory() as db:
            result = await db.execute(
                select(RelayMessage)
                .where(RelayMessage.session_id == session_id)
                .order_by(RelayMessage.seq.asc())
                .limit(limit)
                .offset(offset)
            )
            return [self._message_to_dict(m) for m in result.scalars().all()]

    async def delete_session(self, session_id: str) -> bool:
        async with self._factory() as db:
            result = await db.execute(
                delete(RelaySession).where(RelaySession.id == session_id)
            )
            await db.commit()
            return (result.rowcount or 0) > 0

    # -- helpers --

    @staticmethod
    def _session_to_dict(rec: RelaySession) -> dict[str, Any]:
        return {
            "session_id": rec.id,
            "user_id": str(rec.user_id),
            "title": rec.title,
            "model": rec.model,
            "status": rec.status,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
            "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
            "closed_at": rec.closed_at.isoformat() if rec.closed_at else None,
        }

    @staticmethod
    def _message_to_dict(msg: RelayMessage) -> dict[str, Any]:
        return {
            "id": msg.id,
            "session_id": msg.session_id,
            "seq": msg.seq,
            "direction": msg.direction,
            "method": msg.method,
            "payload": msg.payload,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }
