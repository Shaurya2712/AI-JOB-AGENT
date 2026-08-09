"""Add Telegram destinations and idempotency log.

Revision ID: 20260809_0008
Revises: 20260809_0007
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0008"
down_revision: str | None = "20260809_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_destinations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "telegram_chat_id",
            sa.String(length=32),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('recommendation', 'application_activity', 'scan_summary')",
            name="ck_notification_destinations_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("type", name="uq_notification_destinations_type"),
    )
    op.create_index(
        "ix_notification_destinations_enabled",
        "notification_destinations",
        ["is_enabled"],
    )
    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("destination_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("scan_run_id", sa.Integer(), nullable=True),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=10),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_notification_log_status",
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["notification_destinations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "destination_id",
            "event_key",
            name="uq_notification_log_destination_event",
        ),
    )
    op.create_index(
        "ix_notification_log_destination_id",
        "notification_log",
        ["destination_id"],
    )
    op.create_index("ix_notification_log_job_id", "notification_log", ["job_id"])
    op.create_index("ix_notification_log_status", "notification_log", ["status"])


def downgrade() -> None:
    op.drop_index("ix_notification_log_status", table_name="notification_log")
    op.drop_index("ix_notification_log_job_id", table_name="notification_log")
    op.drop_index("ix_notification_log_destination_id", table_name="notification_log")
    op.drop_table("notification_log")
    op.drop_index(
        "ix_notification_destinations_enabled",
        table_name="notification_destinations",
    )
    op.drop_table("notification_destinations")
