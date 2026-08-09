from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utc_now


SuggestionType = Literal["skill", "role"]
SuggestionStatus = Literal["pending", "accepted", "rejected"]


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    years_experience: Mapped[float] = mapped_column(Float, default=0)
    target_roles_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    role_synonyms_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    skills_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_locations_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    work_modes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    minimum_salary: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(3), default="INR")
    excluded_keywords_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    suggestions: Mapped[list["ProfileSuggestion"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by=lambda: ProfileSuggestion.id.desc(),
    )


class ProfileSuggestion(Base):
    __tablename__ = "profile_suggestions"
    __table_args__ = (
        CheckConstraint("suggestion_type IN ('skill', 'role')", name="ck_profile_suggestion_type"),
        CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name="ck_profile_suggestion_status"),
        Index("ix_profile_suggestions_profile_status", "profile_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    suggestion_type: Mapped[str] = mapped_column(String(10))
    value: Mapped[str] = mapped_column(String(120))
    rationale: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    profile: Mapped[CandidateProfile] = relationship(back_populates="suggestions")
