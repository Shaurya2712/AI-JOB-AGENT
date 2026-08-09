import asyncio
from pathlib import Path

import httpx
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models.profiles import CandidateProfile, ProfileSuggestion
from app.schemas.profiles import CandidateProfileInput, ProfileSuggestionInput
from app.services.profiles import ProfileService


def build_test_app(database_path: Path):
    return create_app(
        Settings(
            environment="test",
            database_url=f"sqlite:///{database_path.as_posix()}",
            log_level="WARNING",
        )
    )


def profile_form(name: str, *, target_roles: str, notes: str = "") -> dict[str, object]:
    return {
        "name": name,
        "is_active": "on",
        "years_experience": "5.5",
        "target_roles": target_roles,
        "role_synonyms": "Mobile Developer\nMobile Engineer",
        "skills": "Flutter, Dart\nPython",
        "preferred_locations": "India\nBengaluru\nRemote",
        "work_modes": ["Remote", "Hybrid", "Onsite"],
        "minimum_salary": "1800000",
        "salary_currency": "inr",
        "excluded_keywords": "Internship\nEngineering Manager",
        "notes": notes,
    }


def test_multiple_active_profiles_and_all_profile_fields_persist(tmp_path: Path) -> None:
    application = build_test_app(tmp_path / "profiles.db")

    async def scenario() -> None:
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                new_profile_page = await client.get("/profiles/new")
                first = await client.post(
                    "/profiles",
                    data=profile_form(
                        "Mobile roles",
                        target_roles="Flutter Developer\nReact Native Developer",
                        notes="Prioritize product companies.",
                    ),
                )
                second = await client.post(
                    "/profiles",
                    data=profile_form("AI roles", target_roles="AI Developer, Software Developer"),
                )
                page = await client.get("/profiles")

            assert first.status_code == 303
            assert second.status_code == 303
            assert new_profile_page.status_code == 200
            assert "Software Engineer — Mobile App Development" in new_profile_page.text
            assert page.status_code == 200
            assert "Mobile roles" in page.text
            assert "AI roles" in page.text

            with application.state.session_factory() as session:
                profiles = list(session.scalars(select(CandidateProfile).order_by(CandidateProfile.id)))

                assert len(profiles) == 2
                assert all(profile.is_active for profile in profiles)
                mobile = profiles[0]
                assert mobile.years_experience == 5.5
                assert mobile.target_roles_json == ["Flutter Developer", "React Native Developer"]
                assert mobile.role_synonyms_json == ["Mobile Developer", "Mobile Engineer"]
                assert mobile.skills_json == ["Flutter", "Dart", "Python"]
                assert mobile.preferred_locations_json == ["India", "Bengaluru", "Remote"]
                assert mobile.work_modes_json == ["Remote", "Hybrid", "Onsite"]
                assert str(mobile.minimum_salary) == "1800000.00"
                assert mobile.salary_currency == "INR"
                assert mobile.excluded_keywords_json == ["Internship", "Engineering Manager"]
                assert mobile.notes == "Prioritize product companies."

    asyncio.run(scenario())


def test_profile_edit_updates_fields_and_active_state(tmp_path: Path) -> None:
    application = build_test_app(tmp_path / "profiles.db")

    async def scenario() -> None:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                profile = ProfileService(session).create_profile(
                    CandidateProfileInput(
                        name="Frontend",
                        years_experience=3,
                        target_roles=["React Developer"],
                    )
                )
                profile_id = profile.id

            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                edit_page = await client.get(f"/profiles/{profile_id}/edit")
                response = await client.post(
                    f"/profiles/{profile_id}/edit",
                    data={
                        **profile_form("Frontend and mobile", target_roles="React Developer\nFlutter Developer"),
                        "is_active": "",
                        "years_experience": "4",
                        "notes": "Updated target.",
                    },
                )

            assert edit_page.status_code == 200
            assert "Frontend" in edit_page.text
            assert response.status_code == 303
            with application.state.session_factory() as session:
                updated = session.get(CandidateProfile, profile_id)
                assert updated is not None
                assert updated.name == "Frontend and mobile"
                assert updated.is_active is False
                assert updated.years_experience == 4
                assert updated.target_roles_json == ["React Developer", "Flutter Developer"]
                assert updated.notes == "Updated target."

    asyncio.run(scenario())


def test_suggestions_never_mutate_profile_before_acceptance(tmp_path: Path) -> None:
    application = build_test_app(tmp_path / "profiles.db")

    async def scenario() -> None:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                service = ProfileService(session)
                profile = service.create_profile(
                    CandidateProfileInput(
                        name="Mobile",
                        years_experience=5,
                        target_roles=["Flutter Developer"],
                        skills=["Dart"],
                    )
                )
                profile_id = profile.id
                skill_suggestion = service.record_suggestion(
                    profile_id,
                    ProfileSuggestionInput(
                        suggestion_type="skill",
                        value="Firebase",
                        rationale="Frequently appears with Flutter roles.",
                    ),
                )
                role_suggestion = service.record_suggestion(
                    profile_id,
                    ProfileSuggestionInput(
                        suggestion_type="role",
                        value="Mobile Engineer",
                        rationale="Closely matches the existing target.",
                    ),
                )
                skill_suggestion_id = skill_suggestion.id
                role_suggestion_id = role_suggestion.id

                unchanged = session.get(CandidateProfile, profile_id)
                assert unchanged is not None
                assert unchanged.skills_json == ["Dart"]
                assert unchanged.target_roles_json == ["Flutter Developer"]

            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                review_page = await client.get("/profiles")
                accepted = await client.post(
                    f"/profiles/{profile_id}/suggestions/{skill_suggestion_id}/accept"
                )
                rejected = await client.post(
                    f"/profiles/{profile_id}/suggestions/{role_suggestion_id}/reject"
                )
                repeated = await client.post(
                    f"/profiles/{profile_id}/suggestions/{skill_suggestion_id}/accept"
                )

            assert review_page.status_code == 200
            assert "Firebase" in review_page.text
            assert "Mobile Engineer" in review_page.text
            assert "Accept" in review_page.text
            assert "Reject" in review_page.text
            assert accepted.status_code == 303
            assert rejected.status_code == 303
            assert repeated.status_code == 409

            with application.state.session_factory() as session:
                updated = session.get(CandidateProfile, profile_id)
                suggestions = list(
                    session.scalars(select(ProfileSuggestion).order_by(ProfileSuggestion.id))
                )
                assert updated is not None
                assert updated.skills_json == ["Dart", "Firebase"]
                assert updated.target_roles_json == ["Flutter Developer"]
                assert [suggestion.status for suggestion in suggestions] == ["accepted", "rejected"]

    asyncio.run(scenario())
