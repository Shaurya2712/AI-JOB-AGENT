from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utc_now


if TYPE_CHECKING:
    from app.models.jobs import Job


class PortalJobSource(Base):
    __tablename__ = "portal_job_sources"
    __table_args__ = (
        UniqueConstraint(
            "portal_name",
            "source_job_id",
            name="uq_portal_job_sources_identity",
        ),
        UniqueConstraint(
            "portal_name",
            "original_url",
            name="uq_portal_job_sources_url",
        ),
        CheckConstraint(
            "portal_name IN ('linkedin', 'naukri', 'indeed')",
            name="ck_portal_job_sources_portal_name",
        ),
        CheckConstraint(
            "data_completeness IN ('partial', 'full')",
            name="ck_portal_job_sources_data_completeness",
        ),
        Index("ix_portal_job_sources_last_seen_at", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    portal_name: Mapped[str] = mapped_column(String(10))
    source_job_id: Mapped[str] = mapped_column(String(255))
    original_url: Mapped[str] = mapped_column(String(4000))
    title: Mapped[str] = mapped_column(String(1000))
    company_name: Mapped[str] = mapped_column(String(160))
    location_text: Mapped[str] = mapped_column(String(1000), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    data_completeness: Mapped[str] = mapped_column(String(10), default="partial")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    job: Mapped["Job"] = relationship(back_populates="portal_sources")
