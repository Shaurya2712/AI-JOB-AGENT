from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utc_now


if TYPE_CHECKING:
    from app.models.jobs import Job
    from app.models.profiles import CandidateProfile


class JobMatch(Base):
    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("job_id", "profile_id", name="uq_job_matches_job_profile"),
        CheckConstraint(
            "overall_score BETWEEN 0 AND 100 "
            "AND (role_score IS NULL OR role_score BETWEEN 0 AND 100) "
            "AND (skills_score IS NULL OR skills_score BETWEEN 0 AND 100) "
            "AND (experience_score IS NULL OR experience_score BETWEEN 0 AND 100) "
            "AND (location_score IS NULL OR location_score BETWEEN 0 AND 100) "
            "AND (freshness_score IS NULL OR freshness_score BETWEEN 0 AND 100) "
            "AND (seniority_score IS NULL OR seniority_score BETWEEN 0 AND 100) "
            "AND (salary_score IS NULL OR salary_score BETWEEN 0 AND 100)",
            name="ck_job_matches_score_ranges",
        ),
        CheckConstraint(
            "recommendation_label IN "
            "('Excellent', 'Strong', 'Review', 'Low Priority', 'Partial / Low Confidence')",
            name="ck_job_matches_recommendation_label",
        ),
        Index("ix_job_matches_profile_score", "profile_id", "overall_score"),
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
    ai_provider: Mapped[str] = mapped_column(String(32))
    ai_model: Mapped[str] = mapped_column(String(120))
    scoring_version: Mapped[str] = mapped_column(String(40))
    overall_score: Mapped[int] = mapped_column(Integer)
    role_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skills_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experience_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    freshness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seniority_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommendation_label: Mapped[str] = mapped_column(String(32))
    matching_skills_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_skills_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    concerns_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    suggested_resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_job_hash: Mapped[str] = mapped_column(String(64))
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped["Job"] = relationship(back_populates="matches")
    profile: Mapped["CandidateProfile"] = relationship(back_populates="matches")
