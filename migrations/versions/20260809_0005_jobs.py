"""Add normalized jobs and deduplication identities.

Revision ID: 20260809_0005
Revises: 20260809_0004
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0005"
down_revision: str | None = "20260809_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_job_id", sa.String(length=255), nullable=False),
        sa.Column("canonical_url", sa.String(length=4000), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("normalized_title", sa.String(length=1000), nullable=False),
        sa.Column("location_text", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("city", sa.String(length=160), nullable=True),
        sa.Column("state", sa.String(length=160), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("remote_type", sa.String(length=30), nullable=True),
        sa.Column("employment_type", sa.String(length=40), nullable=True),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("description_hash", sa.String(length=64), nullable=False),
        sa.Column("dedupe_signature", sa.String(length=64), nullable=False),
        sa.Column("salary_min", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("salary_max", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=True),
        sa.Column("experience_min", sa.Float(), nullable=True),
        sa.Column("experience_max", sa.Float(), nullable=True),
        sa.Column("skills_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "consecutive_missing_scans",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "lifecycle_status",
            sa.String(length=20),
            server_default="open",
            nullable=False,
        ),
        sa.Column("source_payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('open', 'possibly_closed', 'closed')",
            name="ck_jobs_lifecycle_status",
        ),
        sa.CheckConstraint(
            "consecutive_missing_scans >= 0",
            name="ck_jobs_missing_scans_nonnegative",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "canonical_url",
            name="uq_jobs_company_canonical_url",
        ),
        sa.UniqueConstraint(
            "company_id",
            "source_type",
            "source_job_id",
            name="uq_jobs_company_source_identity",
        ),
    )
    op.create_index(
        "ix_jobs_company_lifecycle",
        "jobs",
        ["company_id", "lifecycle_status"],
    )
    op.create_index("ix_jobs_dedupe_signature", "jobs", ["dedupe_signature"])
    op.create_index("ix_jobs_description_hash", "jobs", ["description_hash"])
    op.create_index("ix_jobs_last_seen_at", "jobs", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_last_seen_at", table_name="jobs")
    op.drop_index("ix_jobs_description_hash", table_name="jobs")
    op.drop_index("ix_jobs_dedupe_signature", table_name="jobs")
    op.drop_index("ix_jobs_company_lifecycle", table_name="jobs")
    op.drop_table("jobs")
