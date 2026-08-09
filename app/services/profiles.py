from typing import Literal

from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.profiles import CandidateProfile, ProfileSuggestion
from app.repositories.profiles import ProfileRepository
from app.schemas.profiles import CandidateProfileInput, ProfileSuggestionInput, normalize_entries


class ProfileNotFoundError(LookupError):
    pass


class SuggestionNotPendingError(ValueError):
    pass


class ProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = ProfileRepository(session)

    def list_profiles(self) -> list[CandidateProfile]:
        return self.repository.list_profiles()

    def get_profile(self, profile_id: int, *, with_suggestions: bool = False) -> CandidateProfile:
        profile = self.repository.get_profile(profile_id, with_suggestions=with_suggestions)
        if profile is None:
            raise ProfileNotFoundError(f"Profile {profile_id} was not found")
        return profile

    def create_profile(self, data: CandidateProfileInput) -> CandidateProfile:
        profile = CandidateProfile(**self._profile_values(data))
        self.repository.add_profile(profile)
        self.session.commit()
        self.session.refresh(profile)
        return profile

    def update_profile(self, profile_id: int, data: CandidateProfileInput) -> CandidateProfile:
        profile = self.get_profile(profile_id)
        for field, value in self._profile_values(data).items():
            setattr(profile, field, value)
        profile.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(profile)
        return profile

    def record_suggestion(self, profile_id: int, data: ProfileSuggestionInput) -> ProfileSuggestion:
        self.get_profile(profile_id)
        suggestion = ProfileSuggestion(
            profile_id=profile_id,
            suggestion_type=data.suggestion_type,
            value=data.value,
            rationale=data.rationale,
            status="pending",
        )
        self.repository.add_suggestion(suggestion)
        self.session.commit()
        self.session.refresh(suggestion)
        return suggestion

    def decide_suggestion(
        self,
        profile_id: int,
        suggestion_id: int,
        decision: Literal["accept", "reject"],
    ) -> ProfileSuggestion:
        profile = self.get_profile(profile_id)
        suggestion = self.repository.get_suggestion(profile_id, suggestion_id)
        if suggestion is None:
            raise ProfileNotFoundError(f"Suggestion {suggestion_id} was not found")
        if suggestion.status != "pending":
            raise SuggestionNotPendingError("Only pending suggestions can be decided")

        if decision == "accept":
            if suggestion.suggestion_type == "skill":
                profile.skills_json = normalize_entries([*profile.skills_json, suggestion.value])
            else:
                profile.target_roles_json = normalize_entries([*profile.target_roles_json, suggestion.value])
            profile.updated_at = utc_now()
            suggestion.status = "accepted"
        else:
            suggestion.status = "rejected"

        self.session.commit()
        self.session.refresh(suggestion)
        return suggestion

    @staticmethod
    def _profile_values(data: CandidateProfileInput) -> dict[str, object]:
        return {
            "name": data.name,
            "is_active": data.is_active,
            "years_experience": data.years_experience,
            "target_roles_json": data.target_roles,
            "role_synonyms_json": data.role_synonyms,
            "skills_json": data.skills,
            "preferred_locations_json": data.preferred_locations,
            "work_modes_json": data.work_modes,
            "minimum_salary": data.minimum_salary,
            "salary_currency": data.salary_currency,
            "excluded_keywords_json": data.excluded_keywords,
            "notes": data.notes,
        }
