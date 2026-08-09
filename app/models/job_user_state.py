from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utc_now


if TYPE_CHECKING:
    from app.models.jobs import Job
    from app.models.profiles import CandidateProfile


class JobUserState(Base):
    __tablename__ = "job_user_state"
    __table_args__ = (
        UniqueConstraint("job_id", "profile_id", name="uq_job_user_state_job_profile"),
        CheckConstraint(
            "state IN ('new', 'saved', 'applied', 'ignored')",
            name="ck_job_user_state_value",
        ),
        Index("ix_job_user_state_profile_state", "profile_id", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(10), default="new")
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    job: Mapped["Job"] = relationship(back_populates="user_states")
    profile: Mapped["CandidateProfile"] = relationship(back_populates="job_states")
