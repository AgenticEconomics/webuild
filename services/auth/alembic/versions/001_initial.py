"""initial schema

Revision ID: 001
Create Date: 2026-07-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(64), unique=True, nullable=False),
        sa.Column("email", sa.String(256), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), server_default="developer"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column("name", sa.String(128)),
        sa.Column("scopes", JSONB, server_default="[]"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(256)),
        sa.Column("model", sa.String(64)),
        sa.Column("status", sa.String(32), server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_sessions_user", "sessions", ["user_id", "status"])

    op.create_table(
        "sandboxes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("environment_id", sa.String(64)),
        sa.Column("status", sa.String(32), server_default="creating"),
        sa.Column("pod_name", sa.String(128)),
        sa.Column("namespace", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("terminated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_sandboxes_user", "sandboxes", ["user_id", "status"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("user_id", UUID(as_uuid=True)),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource", sa.String(256)),
        sa.Column("details", JSONB),
        sa.Column("source_ip", sa.String(45)),
        sa.Column("result", sa.String(32), nullable=False),
    )
    op.create_index("idx_audit_user", "audit_logs", ["user_id", "timestamp"])
    op.create_index("idx_audit_action", "audit_logs", ["action", "timestamp"])


def downgrade():
    op.drop_table("audit_logs")
    op.drop_table("sandboxes")
    op.drop_table("sessions")
    op.drop_table("api_keys")
    op.drop_table("users")
