"""Add profile-specific job state for dashboard filters.

Revision ID: 20260809_0007
Revises: 20260809_0006
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0007"
down_revision: str | None = "20260809_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_user_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=10), server_default="new", nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resume_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('new', 'saved', 'applied', 'ignored')",
            name="ck_job_user_state_value",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["candidate_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resume_id"],
            ["resumes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "profile_id",
            name="uq_job_user_state_job_profile",
        ),
    )
    op.create_index("ix_job_user_state_job_id", "job_user_state", ["job_id"])
    op.create_index(
        "ix_job_user_state_profile_state",
        "job_user_state",
        ["profile_id", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_user_state_profile_state", table_name="job_user_state")
    op.drop_index("ix_job_user_state_job_id", table_name="job_user_state")
    op.drop_table("job_user_state")
