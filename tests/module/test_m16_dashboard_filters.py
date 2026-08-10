import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from app.config import Settings
from app.main import create_app
from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.job_user_state import JobUserState
from app.models.jobs import Job
from app.models.profiles import CandidateProfile


OBSERVED_AT = datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)


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


def _profile(name: str, role: str) -> CandidateProfile:
    return CandidateProfile(
        name=name,
        is_active=True,
        years_experience=5,
        target_roles_json=[role],
        role_synonyms_json=[],
        skills_json=[],
        preferred_locations_json=["India"],
        work_modes_json=["Remote", "Hybrid", "Onsite"],
        excluded_keywords_json=[],
        notes="",
    )


def _job(
    company_id: int,
    source_job_id: str,
    title: str,
    *,
    city: str,
    remote_type: str,
    lifecycle: str = "open",
    source_type: str = "greenhouse",
    salary_min: Decimal | None = Decimal("1500000"),
) -> Job:
    return Job(
        company_id=company_id,
        source_type=source_type,
        source_job_id=source_job_id,
        canonical_url=f"https://jobs.example.com/{source_job_id}",
        title=title,
        normalized_title=title.casefold(),
        location_text=f"{city}, India",
        city=city,
        country="India",
        remote_type=remote_type,
        employment_type="full-time",
        description=f"Build products as {title}.",
        description_hash=source_job_id.ljust(64, "a")[:64],
        dedupe_signature=source_job_id.ljust(64, "b")[:64],
        salary_min=salary_min,
        salary_max=(salary_min + Decimal("500000") if salary_min else None),
        salary_currency="INR" if salary_min else None,
        posted_at=OBSERVED_AT,
        discovered_at=OBSERVED_AT,
        last_seen_at=OBSERVED_AT,
        consecutive_missing_scans=0,
        lifecycle_status=lifecycle,
    )


def _match(job_id: int, profile_id: int, score: int) -> JobMatch:
    if score >= 90:
        label = "Excellent"
    elif score >= 85:
        label = "Strong"
    elif score >= 75:
        label = "Review"
    else:
        label = "Low Priority"
    return JobMatch(
        job_id=job_id,
        profile_id=profile_id,
        ai_provider="fake",
        ai_model="fixture",
        scoring_version="job-match-v1",
        overall_score=score,
        role_score=score,
        skills_score=score,
        experience_score=score,
        location_score=score,
        freshness_score=score,
        seniority_score=score,
        salary_score=score,
        recommendation_label=label,
        matching_skills_json=[],
        missing_skills_json=[],
        concerns_json=[],
        explanation="Fixture score.",
        suggested_resume_id=None,
        source_job_hash=str(job_id).rjust(64, "0"),
        scored_at=OBSERVED_AT,
    )


def _seed_filter_scenarios(session) -> tuple[CandidateProfile, CandidateProfile]:
    company = Company(
        name="Acme",
        website_url="https://acme.example",
        careers_url="https://jobs.acme.example",
        provider_type="greenhouse",
        provider_identifier="acme",
        discovery_source="seed",
        is_active=True,
        provider_supported=True,
        total_jobs_seen=0,
    )
    mobile = _profile("Mobile", "Mobile Engineer")
    backend = _profile("Backend", "Backend Engineer")
    session.add_all([company, mobile, backend])
    session.flush()

    strong_new = _job(
        company.id,
        "job-1",
        "Senior Mobile Engineer",
        city="Pune",
        remote_type="remote",
    )
    applied = _job(
        company.id,
        "job-2",
        "Mobile Platform Engineer",
        city="Bengaluru",
        remote_type="onsite",
    )
    ignored = _job(
        company.id,
        "job-3",
        "React Native Developer",
        city="Pune",
        remote_type="hybrid",
    )
    closed = _job(
        company.id,
        "job-4",
        "Mobile Lead",
        city="Pune",
        remote_type="remote",
        lifecycle="closed",
    )
    saved = _job(
        company.id,
        "job-5",
        "Backend Engineer",
        city="Pune",
        remote_type="remote",
        source_type="lever",
    )
    session.add_all([strong_new, applied, ignored, closed, saved])
    session.flush()
    session.add_all(
        [
            _match(strong_new.id, mobile.id, 92),
            _match(applied.id, mobile.id, 87),
            _match(ignored.id, mobile.id, 82),
            _match(closed.id, mobile.id, 95),
            _match(saved.id, backend.id, 89),
            JobUserState(job_id=applied.id, profile_id=mobile.id, state="applied"),
            JobUserState(job_id=ignored.id, profile_id=mobile.id, state="ignored"),
            JobUserState(job_id=saved.id, profile_id=backend.id, state="saved"),
        ]
    )
    session.commit()
    return mobile, backend


def test_dashboard_and_score_filter_show_open_85_plus_jobs(tmp_path: Path) -> None:
    application = _app(tmp_path, "m16-dashboard.db")

    async def scenario() -> tuple[httpx.Response, httpx.Response]:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                _seed_filter_scenarios(session)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                return (
                    await client.get("/"),
                    await client.get("/jobs?min_score=85&lifecycle=open"),
                )

    response, filtered = asyncio.run(scenario())

    assert response.status_code == 200
    assert 'data-metric="apply-today">2<' in response.text
    assert 'data-metric="strong-matches">3<' in response.text
    assert 'data-metric="new-jobs">1<' in response.text
    assert 'data-metric="applied">1<' in response.text
    assert "Senior Mobile Engineer" in response.text
    assert "Backend Engineer" in response.text
    assert "Mobile Platform Engineer" in response.text
    assert "92%" in response.text
    assert "Excellent" in response.text
    assert filtered.status_code == 200
    assert "Senior Mobile Engineer" in filtered.text
    assert "Mobile Platform Engineer" in filtered.text
    assert "Backend Engineer" in filtered.text
    assert "Mobile Lead" not in filtered.text
    assert "React Native Developer" not in filtered.text


def test_jobs_filters_profile_state_location_and_frozen_fields(tmp_path: Path) -> None:
    application = _app(tmp_path, "m16-filters.db")

    async def scenario() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                mobile, _ = _seed_filter_scenarios(session)
                mobile_id = mobile.id
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                applied = await client.get(
                    "/jobs",
                    params={
                        "profile_id": mobile_id,
                        "role": "Mobile",
                        "min_score": 85,
                        "location_mode": "onsite",
                        "city": "Bengaluru",
                        "source": "greenhouse",
                        "lifecycle": "open",
                        "state": "applied",
                        "minimum_salary": 1_000_000,
                        "posted_after": "2026-08-01",
                        "discovered_after": "2026-08-01",
                    },
                )
                ignored = await client.get(
                    "/jobs",
                    params={
                        "profile_id": mobile_id,
                        "min_score": 80,
                        "location_mode": "hybrid",
                        "city": "Pune",
                        "state": "ignored",
                    },
                )
                remote = await client.get(
                    "/jobs",
                    params={
                        "role": "Backend",
                        "source": "lever",
                        "state": "saved",
                        "remote": "true",
                    },
                )
                return applied, ignored, remote

    applied, ignored, remote = asyncio.run(scenario())

    assert applied.status_code == ignored.status_code == remote.status_code == 200
    assert "Mobile Platform Engineer" in applied.text
    assert "Senior Mobile Engineer" not in applied.text
    assert "React Native Developer" in ignored.text
    assert "Mobile Platform Engineer" not in ignored.text
    assert "Backend Engineer" in remote.text
    assert "Senior Mobile Engineer" not in remote.text
    for field_name in (
        "profile_id",
        "role",
        "min_score",
        "location_mode",
        "city",
        "source",
        "lifecycle",
        "state",
        "minimum_salary",
        "remote",
        "posted_after",
        "discovered_after",
    ):
        assert f'name="{field_name}"' in applied.text


def test_jobs_filter_form_accepts_blank_optional_values(tmp_path: Path) -> None:
    application = _app(tmp_path, "m16-blank-filter-values.db")

    async def scenario() -> httpx.Response:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                _seed_filter_scenarios(session)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                return await client.get(
                    "/jobs",
                    params={
                        "profile_id": "",
                        "role": "",
                        "min_score": "",
                        "location_mode": "",
                        "city": "",
                        "source": "",
                        "lifecycle": "open",
                        "state": "",
                        "minimum_salary": "600000",
                        "posted_after": "",
                        "discovered_after": "",
                    },
                )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    assert "Senior Mobile Engineer" in response.text
    assert 'name="minimum_salary"' in response.text
    assert 'value="600000"' in response.text


def test_jobs_are_paginated_at_twenty_five_rows(tmp_path: Path) -> None:
    application = _app(tmp_path, "m16-pagination.db")

    async def scenario() -> tuple[httpx.Response, httpx.Response]:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                company = Company(
                    name="Pagination Co",
                    website_url="https://pagination.example",
                    careers_url="https://pagination.example/jobs",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                )
                session.add(company)
                session.flush()
                session.add_all(
                    [
                        _job(
                            company.id,
                            f"page-{index}",
                            f"Pagination Job {index:02d}",
                            city="Pune",
                            remote_type="remote",
                            salary_min=None,
                        )
                        for index in range(26)
                    ]
                )
                session.commit()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                return await client.get("/jobs"), await client.get("/jobs?page=2")

    first, second = asyncio.run(scenario())

    assert first.status_code == second.status_code == 200
    assert first.text.count("data-job-id=") == 25
    assert second.text.count("data-job-id=") == 1
    assert "Page 1 of 2" in first.text
    assert "Page 2 of 2" in second.text
    assert ">Next<" in first.text
    assert ">Previous<" in second.text
