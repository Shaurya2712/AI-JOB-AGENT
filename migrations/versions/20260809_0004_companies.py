"""Add the company registry.

Revision ID: 20260809_0004
Revises: 20260809_0003
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0004"
down_revision: str | None = "20260809_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("website_url", sa.String(length=500), nullable=False),
        sa.Column("careers_url", sa.String(length=1000), nullable=True),
        sa.Column("provider_type", sa.String(length=40), nullable=True),
        sa.Column("provider_identifier", sa.String(length=255), nullable=True),
        sa.Column("discovery_source", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("provider_supported", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_jobs_seen", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("website_url"),
    )
    op.create_index("ix_companies_is_active", "companies", ["is_active"])
    op.create_index("ix_companies_provider_type", "companies", ["provider_type"])


def downgrade() -> None:
    op.drop_index("ix_companies_provider_type", table_name="companies")
    op.drop_index("ix_companies_is_active", table_name="companies")
    op.drop_table("companies")
