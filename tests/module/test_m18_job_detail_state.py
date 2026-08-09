import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.job_user_state import JobUserState
from app.models.jobs import Job
from app.models.profiles import CandidateProfile
from app.models.resumes import Resume
from app.providers.jobs.base import ConnectorJob
from app.services.jobs import JobUpsertService


OBSERVED_AT = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)


def _app(tmp_path: Path, name: str):
    seed_path = tmp_path / f"{name}-seed.json"
    seed_path.write_text("[]", encoding="utf-8")
    return create_app(
        Settings(
            environment="test",
            database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
            company_seed_path=seed_path,
            resume_storage_path=tmp_path / "resumes",
            ai_provider="disabled",
        )
    )


def _profile(name: str) -> CandidateProfile:
    return CandidateProfile(
        name=name,
        is_active=True,
        years_experience=6,
        target_roles_json=["Mobile Engineer"],
        role_synonyms_json=["React Native Developer"],
        skills_json=["React Native", "TypeScript"],
        preferred_locations_json=["Pune", "Remote"],
        work_modes_json=["Remote", "Hybrid"],
        minimum_salary=1_500_000,
        salary_currency="INR",
        excluded_keywords_json=[],
        notes="",
    )


def _seed(session) -> tuple[int, int, int, int]:
    company = Company(
        name="Detail Co",
        website_url="https://detail.example",
        careers_url="https://detail.example/jobs",
        provider_type="greenhouse",
        provider_identifier="detail",
        discovery_source="seed",
        is_active=True,
        provider_supported=True,
        total_jobs_seen=1,
    )
    profile = _profile("Mobile Profile")
    other_profile = _profile("Other Profile")
    session.add_all([company, profile, other_profile])
    session.flush()

    resume = Resume(
        profile_id=profile.id,
        name="Mobile Resume",
        file_path="profiles/mobile-resume.txt",
        extracted_text="React Native and TypeScript experience.",
        is_primary=True,
    )
    other_resume = Resume(
        profile_id=other_profile.id,
        name="Other Resume",
        file_path="profiles/other-resume.txt",
        extracted_text="Unrelated resume.",
        is_primary=True,
    )
    session.add_all([resume, other_resume])
    session.flush()

    job = Job(
        company_id=company.id,
        source_type="greenhouse",
        source_job_id="detail-1",
        canonical_url="https://jobs.example.com/detail-1",
        title="Senior Mobile Engineer",
        normalized_title="senior mobile engineer",
        location_text="Pune, India",
        city="Pune",
        country="India",
        remote_type="hybrid",
        employment_type="full-time",
        description="Build a thoughtful mobile platform.\nWork with product partners.",
        description_hash="a" * 64,
        dedupe_signature="b" * 64,
        salary_min=1_800_000,
        salary_max=2_400_000,
        salary_currency="INR",
        experience_min=4,
        experience_max=7,
        skills_json=["React Native", "TypeScript", "GraphQL"],
        posted_at=OBSERVED_AT - timedelta(days=2),
        discovered_at=OBSERVED_AT,
        last_seen_at=OBSERVED_AT,
        consecutive_missing_scans=0,
        lifecycle_status="open",
    )
    session.add(job)
    session.flush()
    match = JobMatch(
        job_id=job.id,
        profile_id=profile.id,
        ai_provider="fake",
        ai_model="fixture",
        scoring_version="job-match-v1",
        overall_score=91,
        role_score=95,
        skills_score=90,
        experience_score=88,
        location_score=94,
        freshness_score=86,
        seniority_score=89,
        salary_score=92,
        recommendation_label="Excellent",
        matching_skills_json=["React Native", "TypeScript"],
        missing_skills_json=["GraphQL"],
        concerns_json=["Confirm hybrid schedule"],
        explanation="Strong mobile role, skills, and location fit.",
        suggested_resume_id=resume.id,
        source_job_hash="c" * 64,
        scored_at=OBSERVED_AT,
    )
    session.add(match)
    session.commit()
    return job.id, profile.id, resume.id, other_resume.id


def test_job_detail_renders_decision_information_and_internal_links(
    tmp_path: Path,
) -> None:
    application = _app(tmp_path, "m18-detail.db")

    async def scenario() -> tuple[httpx.Response, httpx.Response]:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                job_id, profile_id, _, _ = _seed(session)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                return (
                    await client.get("/jobs"),
                    await client.get(f"/jobs/{job_id}?profile_id={profile_id}"),
                )

    jobs, detail = asyncio.run(scenario())

    assert jobs.status_code == detail.status_code == 200
    assert 'href="/jobs/1?profile_id=1"' in jobs.text
    for expected in (
        "Senior Mobile Engineer",
        "Detail Co",
        "Pune, India",
        "Open Original Job",
        "https://jobs.example.com/detail-1",
        "91%",
        "Excellent",
        "Strong mobile role, skills, and location fit.",
        "React Native",
        "GraphQL",
        "Confirm hybrid schedule",
        "Mobile Profile",
        "Mobile Resume",
        "Suggested",
        "INR 1,800,000–2,400,000",
        "4–7 years",
        "Build a thoughtful mobile platform.",
        "State: New",
        "Save",
        "Mark Applied",
        "Ignore",
    ):
        assert expected in detail.text
    assert 'target="_blank" rel="noopener noreferrer"' in detail.text


def test_state_actions_and_application_metadata_survive_rediscovery(
    tmp_path: Path,
) -> None:
    application = _app(tmp_path, "m18-state.db")

    async def scenario() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                job_id, profile_id, resume_id, other_resume_id = _seed(session)
                company_id = session.get(Job, job_id).company_id
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                saved = await client.post(
                    f"/jobs/{job_id}/state",
                    data={"profile_id": profile_id, "action": "saved"},
                )
                assert saved.status_code == 303
                applied = await client.post(
                    f"/jobs/{job_id}/state",
                    data={
                        "profile_id": profile_id,
                        "action": "applied",
                        "resume_id": resume_id,
                        "note": "Applied through the company portal.",
                    },
                )
                assert applied.status_code == 303

                with application.state.session_factory() as session:
                    before = session.scalar(
                        select(JobUserState).where(
                            JobUserState.job_id == job_id,
                            JobUserState.profile_id == profile_id,
                        )
                    )
                    assert before is not None
                    assert before.state == "applied"
                    assert before.applied_at is not None
                    applied_at = before.applied_at
                    JobUpsertService(session).upsert(
                        company_id,
                        ConnectorJob(
                            source_type="greenhouse",
                            source_job_id="detail-1",
                            title="Senior Mobile Engineer",
                            location_text="Pune, India",
                            description="Updated mobile platform description.",
                            job_url="https://jobs.example.com/detail-1",
                        ),
                        seen_at=OBSERVED_AT + timedelta(days=1),
                    )

                after_rediscovery = await client.get(
                    f"/jobs/{job_id}?profile_id={profile_id}"
                )
                invalid_resume = await client.post(
                    f"/jobs/{job_id}/state",
                    data={
                        "profile_id": profile_id,
                        "action": "applied",
                        "resume_id": other_resume_id,
                    },
                )
                assert invalid_resume.status_code == 422
                ignored = await client.post(
                    f"/jobs/{job_id}/state",
                    data={"profile_id": profile_id, "action": "ignored"},
                )
                assert ignored.status_code == 303

            with application.state.session_factory() as session:
                state = session.scalar(
                    select(JobUserState).where(
                        JobUserState.job_id == job_id,
                        JobUserState.profile_id == profile_id,
                    )
                )
                assert state is not None
                assert state.state == "ignored"
                assert state.applied_at == applied_at
                assert state.resume_id == resume_id
                assert state.note == "Applied through the company portal."
                assert session.get(Job, job_id).description == (
                    "Updated mobile platform description."
                )
            return saved, applied, after_rediscovery

    saved, applied, detail = asyncio.run(scenario())

    assert saved.headers["location"] == "/jobs/1?profile_id=1"
    assert applied.headers["location"] == "/jobs/1?profile_id=1"
    assert detail.status_code == 200
    assert "State: Applied" in detail.text
    assert "Applied through the company portal." in detail.text
    assert "Updated mobile platform description." in detail.text
