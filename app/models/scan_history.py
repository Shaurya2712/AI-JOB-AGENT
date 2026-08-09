from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


if TYPE_CHECKING:
    from app.models.companies import Company


class ScanRun(Base):
    __tablename__ = "scan_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('manual', 'scheduled')",
            name="ck_scan_runs_trigger_type",
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'partial', 'failed')",
            name="ck_scan_runs_status",
        ),
        CheckConstraint(
            "companies_checked >= 0 AND sources_checked >= 0 "
            "AND jobs_fetched >= 0 AND jobs_new >= 0 AND jobs_updated >= 0 "
            "AND jobs_scored >= 0 AND strong_matches >= 0 AND errors_count >= 0",
            name="ck_scan_runs_counts_nonnegative",
        ),
        Index("ix_scan_runs_started_at", "started_at"),
        Index("ix_scan_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger_type: Mapped[str] = mapped_column(String(10))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(10), default="running")
    companies_checked: Mapped[int] = mapped_column(Integer, default=0)
    sources_checked: Mapped[int] = mapped_column(Integer, default=0)
    jobs_fetched: Mapped[int] = mapped_column(Integer, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0)
    jobs_updated: Mapped[int] = mapped_column(Integer, default=0)
    jobs_scored: Mapped[int] = mapped_column(Integer, default=0)
    strong_matches: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="Scan is running.")

    source_results: Mapped[list["ScanSourceResult"]] = relationship(
        back_populates="scan_run",
        cascade="all, delete-orphan",
    )


class ScanSourceResult(Base):
    __tablename__ = "scan_source_results"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_scan_source_results_status",
        ),
        CheckConstraint(
            "jobs_fetched >= 0 AND jobs_new >= 0 AND jobs_updated >= 0 "
            "AND retry_count >= 0",
            name="ck_scan_source_results_counts_nonnegative",
        ),
        Index("ix_scan_source_results_run_status", "scan_run_id", "status"),
        Index("ix_scan_source_results_finished_at", "finished_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10))
    jobs_fetched: Mapped[int] = mapped_column(Integer, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0)
    jobs_updated: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    scan_run: Mapped[ScanRun] = relationship(back_populates="source_results")
    company: Mapped["Company | None"] = relationship()
