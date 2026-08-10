"""Add canonical portal persistence and alternate source observations.

Revision ID: 20260810_0011
Revises: 20260809_0010
Create Date: 2026-08-10
"""

from collections.abc import Sequence
from hashlib import sha256
import re
import unicodedata

from alembic import op
import sqlalchemy as sa


revision: str = "20260810_0011"
down_revision: str | None = "20260809_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def upgrade() -> None:
    op.add_column("jobs", sa.Column("company_name", sa.String(length=160), nullable=True))
    op.add_column(
        "jobs",
        sa.Column(
            "data_completeness",
            sa.String(length=10),
            server_default="full",
            nullable=False,
        ),
    )
    op.add_column(
        "jobs",
        sa.Column("cross_source_signature", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE jobs SET company_name = "
            "(SELECT companies.name FROM companies WHERE companies.id = jobs.company_id)"
        )
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, company_name, title, location_text FROM jobs ORDER BY id"
        )
    ).mappings()
    for row in rows:
        signature = _cross_source_signature(
            row["company_name"],
            row["title"],
            row["location_text"],
        )
        if signature is not None:
            connection.execute(
                sa.text(
                    "UPDATE jobs SET cross_source_signature = :signature WHERE id = :job_id"
                ),
                {"signature": signature, "job_id": row["id"]},
            )

    with op.batch_alter_table(
        "jobs",
        recreate="always",
        naming_convention=_FK_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.alter_column(
            "company_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.alter_column(
            "company_name",
            existing_type=sa.String(length=160),
            nullable=False,
        )
        batch_op.drop_constraint(
            "fk_jobs_company_id_companies",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_jobs_company_id_companies",
            "companies",
            ["company_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_jobs_data_completeness",
            "data_completeness IN ('partial', 'full')",
        )

    op.create_index(
        "ix_jobs_cross_source_signature",
        "jobs",
        ["cross_source_signature"],
    )

    with op.batch_alter_table("job_matches", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_job_matches_score_ranges", type_="check")
        batch_op.drop_constraint(
            "ck_job_matches_recommendation_label",
            type_="check",
        )
        for column_name in (
            "role_score",
            "skills_score",
            "experience_score",
            "location_score",
            "freshness_score",
            "seniority_score",
        ):
            batch_op.alter_column(
                column_name,
                existing_type=sa.Integer(),
                nullable=True,
            )
        batch_op.alter_column(
            "recommendation_label",
            existing_type=sa.String(length=20),
            type_=sa.String(length=32),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_job_matches_score_ranges",
            "overall_score BETWEEN 0 AND 100 "
            "AND (role_score IS NULL OR role_score BETWEEN 0 AND 100) "
            "AND (skills_score IS NULL OR skills_score BETWEEN 0 AND 100) "
            "AND (experience_score IS NULL OR experience_score BETWEEN 0 AND 100) "
            "AND (location_score IS NULL OR location_score BETWEEN 0 AND 100) "
            "AND (freshness_score IS NULL OR freshness_score BETWEEN 0 AND 100) "
            "AND (seniority_score IS NULL OR seniority_score BETWEEN 0 AND 100) "
            "AND (salary_score IS NULL OR salary_score BETWEEN 0 AND 100)",
        )
        batch_op.create_check_constraint(
            "ck_job_matches_recommendation_label",
            "recommendation_label IN "
            "('Excellent', 'Strong', 'Review', 'Low Priority', "
            "'Partial / Low Confidence')",
        )

    op.create_table(
        "portal_job_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("portal_name", sa.String(length=10), nullable=False),
        sa.Column("source_job_id", sa.String(length=255), nullable=False),
        sa.Column("original_url", sa.String(length=4000), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("company_name", sa.String(length=160), nullable=False),
        sa.Column("location_text", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("snippet", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "data_completeness",
            sa.String(length=10),
            server_default="partial",
            nullable=False,
        ),
        sa.Column(
            "first_seen_at",
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
        sa.CheckConstraint(
            "data_completeness IN ('partial', 'full')",
            name="ck_portal_job_sources_data_completeness",
        ),
        sa.CheckConstraint(
            "portal_name IN ('linkedin', 'naukri', 'indeed')",
            name="ck_portal_job_sources_portal_name",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "portal_name",
            "source_job_id",
            name="uq_portal_job_sources_identity",
        ),
        sa.UniqueConstraint(
            "portal_name",
            "original_url",
            name="uq_portal_job_sources_url",
        ),
    )
    op.create_index(
        "ix_portal_job_sources_job_id",
        "portal_job_sources",
        ["job_id"],
    )
    op.create_index(
        "ix_portal_job_sources_last_seen_at",
        "portal_job_sources",
        ["last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portal_job_sources_last_seen_at",
        table_name="portal_job_sources",
    )
    op.drop_index("ix_portal_job_sources_job_id", table_name="portal_job_sources")
    op.drop_table("portal_job_sources")

    op.execute(
        sa.text(
            "DELETE FROM job_matches WHERE recommendation_label = "
            "'Partial / Low Confidence' OR role_score IS NULL OR skills_score IS NULL "
            "OR experience_score IS NULL OR location_score IS NULL "
            "OR freshness_score IS NULL OR seniority_score IS NULL"
        )
    )
    with op.batch_alter_table("job_matches", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_job_matches_score_ranges", type_="check")
        batch_op.drop_constraint(
            "ck_job_matches_recommendation_label",
            type_="check",
        )
        for column_name in (
            "role_score",
            "skills_score",
            "experience_score",
            "location_score",
            "freshness_score",
            "seniority_score",
        ):
            batch_op.alter_column(
                column_name,
                existing_type=sa.Integer(),
                nullable=False,
            )
        batch_op.alter_column(
            "recommendation_label",
            existing_type=sa.String(length=32),
            type_=sa.String(length=20),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_job_matches_score_ranges",
            "overall_score BETWEEN 0 AND 100 "
            "AND role_score BETWEEN 0 AND 100 "
            "AND skills_score BETWEEN 0 AND 100 "
            "AND experience_score BETWEEN 0 AND 100 "
            "AND location_score BETWEEN 0 AND 100 "
            "AND freshness_score BETWEEN 0 AND 100 "
            "AND seniority_score BETWEEN 0 AND 100 "
            "AND (salary_score IS NULL OR salary_score BETWEEN 0 AND 100)",
        )
        batch_op.create_check_constraint(
            "ck_job_matches_recommendation_label",
            "recommendation_label IN ('Excellent', 'Strong', 'Review', 'Low Priority')",
        )

    op.drop_index("ix_jobs_cross_source_signature", table_name="jobs")
    op.execute(sa.text("DELETE FROM jobs WHERE company_id IS NULL"))
    with op.batch_alter_table(
        "jobs",
        recreate="always",
        naming_convention=_FK_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint("ck_jobs_data_completeness", type_="check")
        batch_op.drop_constraint(
            "fk_jobs_company_id_companies",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_jobs_company_id_companies",
            "companies",
            ["company_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.alter_column(
            "company_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.drop_column("cross_source_signature")
        batch_op.drop_column("data_completeness")
        batch_op.drop_column("company_name")


def _cross_source_signature(
    company_name: object,
    title: object,
    location: object,
) -> str | None:
    employer_key = _employer_key(str(company_name or ""))
    title_key = _identity_text(str(title or ""))
    location_key = _location_key(str(location or ""))
    if not employer_key or not title_key or not location_key:
        return None
    value = "\0".join((employer_key, title_key, location_key))
    return sha256(value.encode("utf-8")).hexdigest()


def _employer_key(value: str) -> str:
    tokens = _identity_text(value).split()
    suffixes = (
        ("private", "limited"),
        ("pvt", "ltd"),
        ("incorporated",),
        ("corporation",),
        ("company",),
        ("limited",),
        ("corp",),
        ("inc",),
        ("llp",),
        ("ltd",),
        ("co",),
    )
    for suffix in suffixes:
        if tuple(tokens[-len(suffix) :]) == suffix:
            tokens = tokens[: -len(suffix)]
            break
    return " ".join(tokens)


def _location_key(value: str) -> str:
    key = _identity_text(value)
    aliases = {
        "bangalore": "bengaluru",
        "bangalore india": "bengaluru india",
        "bangalore karnataka": "bengaluru karnataka",
        "bangalore karnataka india": "bengaluru karnataka india",
    }
    return aliases.get(key, key)


def _identity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w+#.]+", " ", normalized).split())
