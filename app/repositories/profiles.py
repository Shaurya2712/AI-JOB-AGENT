from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.profiles import CandidateProfile, ProfileSuggestion
from app.models.resumes import Resume


class ProfileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_profiles(self) -> list[CandidateProfile]:
        statement = (
            select(CandidateProfile)
            .options(
                selectinload(CandidateProfile.suggestions),
                selectinload(CandidateProfile.resumes),
            )
            .order_by(CandidateProfile.is_active.desc(), CandidateProfile.name, CandidateProfile.id)
        )
        return list(self.session.scalars(statement).all())

    def list_active_profiles(self) -> list[CandidateProfile]:
        statement = (
            select(CandidateProfile)
            .where(CandidateProfile.is_active.is_(True))
            .order_by(CandidateProfile.name, CandidateProfile.id)
        )
        return list(self.session.scalars(statement).all())

    def get_profile(self, profile_id: int, *, with_suggestions: bool = False) -> CandidateProfile | None:
        statement = select(CandidateProfile).where(CandidateProfile.id == profile_id)
        if with_suggestions:
            statement = statement.options(
                selectinload(CandidateProfile.suggestions),
                selectinload(CandidateProfile.resumes),
            )
        return self.session.scalar(statement)

    def add_profile(self, profile: CandidateProfile) -> None:
        self.session.add(profile)

    def add_suggestion(self, suggestion: ProfileSuggestion) -> None:
        self.session.add(suggestion)

    def get_suggestion(self, profile_id: int, suggestion_id: int) -> ProfileSuggestion | None:
        statement = select(ProfileSuggestion).where(
            ProfileSuggestion.id == suggestion_id,
            ProfileSuggestion.profile_id == profile_id,
        )
        return self.session.scalar(statement)
