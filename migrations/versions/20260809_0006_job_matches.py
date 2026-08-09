"""Add persisted AI job matches.

Revision ID: 20260809_0006
Revises: 20260809_0005
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0006"
down_revision: str | None = "20260809_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("ai_provider", sa.String(length=32), nullable=False),
        sa.Column("ai_model", sa.String(length=120), nullable=False),
        sa.Column("scoring_version", sa.String(length=40), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("role_score", sa.Integer(), nullable=False),
        sa.Column("skills_score", sa.Integer(), nullable=False),
        sa.Column("experience_score", sa.Integer(), nullable=False),
        sa.Column("location_score", sa.Integer(), nullable=False),
        sa.Column("freshness_score", sa.Integer(), nullable=False),
        sa.Column("seniority_score", sa.Integer(), nullable=False),
        sa.Column("salary_score", sa.Integer(), nullable=True),
        sa.Column("recommendation_label", sa.String(length=20), nullable=False),
        sa.Column(
            "matching_skills_json",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "missing_skills_json",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "concerns_json",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("suggested_resume_id", sa.Integer(), nullable=True),
        sa.Column("source_job_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "scored_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "overall_score BETWEEN 0 AND 100 "
            "AND role_score BETWEEN 0 AND 100 "
            "AND skills_score BETWEEN 0 AND 100 "
            "AND experience_score BETWEEN 0 AND 100 "
            "AND location_score BETWEEN 0 AND 100 "
            "AND freshness_score BETWEEN 0 AND 100 "
            "AND seniority_score BETWEEN 0 AND 100 "
            "AND (salary_score IS NULL OR salary_score BETWEEN 0 AND 100)",
            name="ck_job_matches_score_ranges",
        ),
        sa.CheckConstraint(
            "recommendation_label IN ('Excellent', 'Strong', 'Review', 'Low Priority')",
            name="ck_job_matches_recommendation_label",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["candidate_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["suggested_resume_id"],
            ["resumes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "profile_id",
            name="uq_job_matches_job_profile",
        ),
    )
    op.create_index("ix_job_matches_job_id", "job_matches", ["job_id"])
    op.create_index(
        "ix_job_matches_profile_score",
        "job_matches",
        ["profile_id", "overall_score"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_matches_profile_score", table_name="job_matches")
    op.drop_index("ix_job_matches_job_id", table_name="job_matches")
    op.drop_table("job_matches")
