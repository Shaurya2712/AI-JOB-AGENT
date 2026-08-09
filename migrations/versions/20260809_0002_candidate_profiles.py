"""Add candidate profiles and approval-gated suggestions.

Revision ID: 20260809_0002
Revises: 20260809_0001
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0002"
down_revision: str | None = "20260809_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("years_experience", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("target_roles_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("role_synonyms_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("skills_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("preferred_locations_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("work_modes_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("minimum_salary", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("excluded_keywords_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_profiles_is_active", "candidate_profiles", ["is_active"])

    op.create_table(
        "profile_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("suggestion_type", sa.String(length=10), nullable=False),
        sa.Column("value", sa.String(length=120), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name="ck_profile_suggestion_status"),
        sa.CheckConstraint("suggestion_type IN ('skill', 'role')", name="ck_profile_suggestion_type"),
        sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_profile_suggestions_profile_status",
        "profile_suggestions",
        ["profile_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_profile_suggestions_profile_status", table_name="profile_suggestions")
    op.drop_table("profile_suggestions")
    op.drop_index("ix_candidate_profiles_is_active", table_name="candidate_profiles")
    op.drop_table("candidate_profiles")
