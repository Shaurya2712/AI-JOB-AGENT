from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utc_now


if TYPE_CHECKING:
    from app.models.jobs import Job


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    website_url: Mapped[str] = mapped_column(String(500), unique=True)
    careers_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    provider_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    provider_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discovery_source: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    provider_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_jobs_seen: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    jobs: Mapped[list["Job"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
