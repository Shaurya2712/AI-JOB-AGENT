"""Add persistent scan history and source health.

Revision ID: 20260809_0009
Revises: 20260809_0008
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0009"
down_revision: str | None = "20260809_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trigger_type", sa.String(length=10), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=10),
            server_default="running",
            nullable=False,
        ),
        sa.Column(
            "companies_checked",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("sources_checked", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_fetched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_new", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_scored", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "strong_matches",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("errors_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "summary",
            sa.Text(),
            server_default="Scan is running.",
            nullable=False,
        ),
        sa.CheckConstraint(
            "trigger_type IN ('manual', 'scheduled')",
            name="ck_scan_runs_trigger_type",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'partial', 'failed')",
            name="ck_scan_runs_status",
        ),
        sa.CheckConstraint(
            "companies_checked >= 0 AND sources_checked >= 0 "
            "AND jobs_fetched >= 0 AND jobs_new >= 0 AND jobs_updated >= 0 "
            "AND jobs_scored >= 0 AND strong_matches >= 0 AND errors_count >= 0",
            name="ck_scan_runs_counts_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scan_runs_started_at", "scan_runs", ["started_at"])
    op.create_index("ix_scan_runs_status", "scan_runs", ["status"])

    op.create_table(
        "scan_source_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_run_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("jobs_fetched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_new", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_scan_source_results_status",
        ),
        sa.CheckConstraint(
            "jobs_fetched >= 0 AND jobs_new >= 0 AND jobs_updated >= 0 "
            "AND retry_count >= 0",
            name="ck_scan_source_results_counts_nonnegative",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scan_run_id"], ["scan_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scan_source_results_run_status",
        "scan_source_results",
        ["scan_run_id", "status"],
    )
    op.create_index(
        "ix_scan_source_results_finished_at",
        "scan_source_results",
        ["finished_at"],
    )

    with op.batch_alter_table("notification_log") as batch_op:
        batch_op.create_foreign_key(
            "fk_notification_log_scan_run_id",
            "scan_runs",
            ["scan_run_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("notification_log") as batch_op:
        batch_op.drop_constraint(
            "fk_notification_log_scan_run_id",
            type_="foreignkey",
        )
    op.drop_index(
        "ix_scan_source_results_finished_at",
        table_name="scan_source_results",
    )
    op.drop_index(
        "ix_scan_source_results_run_status",
        table_name="scan_source_results",
    )
    op.drop_table("scan_source_results")
    op.drop_index("ix_scan_runs_status", table_name="scan_runs")
    op.drop_index("ix_scan_runs_started_at", table_name="scan_runs")
    op.drop_table("scan_runs")
