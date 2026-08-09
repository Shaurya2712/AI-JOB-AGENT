from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utc_now


if TYPE_CHECKING:
    from app.models.companies import Company
    from app.models.job_matches import JobMatch
    from app.models.job_user_state import JobUserState


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_status IN ('open', 'possibly_closed', 'closed')",
            name="ck_jobs_lifecycle_status",
        ),
        CheckConstraint(
            "consecutive_missing_scans >= 0",
            name="ck_jobs_missing_scans_nonnegative",
        ),
        UniqueConstraint(
            "company_id",
            "source_type",
            "source_job_id",
            name="uq_jobs_company_source_identity",
        ),
        UniqueConstraint(
            "company_id",
            "canonical_url",
            name="uq_jobs_company_canonical_url",
        ),
        Index("ix_jobs_company_lifecycle", "company_id", "lifecycle_status"),
        Index("ix_jobs_dedupe_signature", "dedupe_signature"),
        Index("ix_jobs_description_hash", "description_hash"),
        Index("ix_jobs_last_seen_at", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(40))
    source_job_id: Mapped[str] = mapped_column(String(255))
    canonical_url: Mapped[str] = mapped_column(String(4000))
    title: Mapped[str] = mapped_column(String(1000))
    normalized_title: Mapped[str] = mapped_column(String(1000))
    location_text: Mapped[str] = mapped_column(String(1000), default="")
    city: Mapped[str | None] = mapped_column(String(160), nullable=True)
    state: Mapped[str | None] = mapped_column(String(160), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remote_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    description_hash: Mapped[str] = mapped_column(String(64))
    dedupe_signature: Mapped[str] = mapped_column(String(64))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    experience_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    skills_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    consecutive_missing_scans: Mapped[int] = mapped_column(Integer, default=0)
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="open")
    source_payload_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    company: Mapped["Company"] = relationship(back_populates="jobs")
    matches: Mapped[list["JobMatch"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )
    user_states: Mapped[list["JobUserState"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )
