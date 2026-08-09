import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.config import Settings
from app.main import create_app
from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.job_user_state import JobUserState
from app.models.jobs import Job
from app.models.profiles import CandidateProfile


OBSERVED_AT = datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc)


def _app(tmp_path: Path, name: str, *, target: int | None = None):
    seed_path = tmp_path / f"{name}-seed.json"
    seed_path.write_text("[]", encoding="utf-8")
    values = {
        "environment": "test",
        "database_url": f"sqlite:///{(tmp_path / name).as_posix()}",
        "company_seed_path": seed_path,
        "resume_storage_path": tmp_path / "resumes",
        "ai_provider": "disabled",
    }
    if target is not None:
        values["daily_action_target"] = target
    return create_app(Settings(**values))


def _profile(name: str, *, active: bool = True) -> CandidateProfile:
    return CandidateProfile(
        name=name,
        is_active=active,
        years_experience=5,
        target_roles_json=["Software Engineer"],
        role_synonyms_json=[],
        skills_json=[],
        preferred_locations_json=["India"],
        work_modes_json=["Remote"],
        excluded_keywords_json=[],
        notes="",
    )


def _job(
    company_id: int,
    number: int,
    title: str,
    *,
    lifecycle: str = "open",
) -> Job:
    identity = f"m17-{number}"
    return Job(
        company_id=company_id,
        source_type="greenhouse",
        source_job_id=identity,
        canonical_url=f"https://jobs.example.com/{identity}",
        title=title,
        normalized_title=title.casefold(),
        location_text="Pune, India",
        city="Pune",
        country="India",
        remote_type="remote",
        employment_type="full-time",
        description=f"Build software for {title}.",
        description_hash=identity.ljust(64, "a")[:64],
        dedupe_signature=identity.ljust(64, "b")[:64],
        salary_min=1_500_000,
        salary_max=2_000_000,
        salary_currency="INR",
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
        source_job_hash=f"{job_id:064d}",
        scored_at=OBSERVED_AT,
    )


def _seed_queue(session) -> None:
    company = Company(
        name="Queue Co",
        website_url="https://queue.example",
        careers_url="https://queue.example/jobs",
        provider_type="greenhouse",
        provider_identifier="queue",
        discovery_source="seed",
        is_active=True,
        provider_supported=True,
        total_jobs_seen=0,
    )
    primary = _profile("Primary")
    secondary = _profile("Secondary")
    inactive = _profile("Inactive", active=False)
    session.add_all([company, primary, secondary, inactive])
    session.flush()

    eligible = [
        _job(company.id, index, title)
        for index, title in enumerate(
            ["Saved Top", "Fresh Second"]
            + [f"Queue Candidate {index:02d}" for index in range(3, 13)],
            start=1,
        )
    ]
    applied = _job(company.id, 20, "Applied Higher")
    ignored = _job(company.id, 21, "Ignored Higher")
    closed = _job(company.id, 22, "Closed Higher", lifecycle="closed")
    unscored = _job(company.id, 23, "Unscored Open")
    inactive_only = _job(company.id, 24, "Inactive Profile Match")
    handled_on_other_profile = _job(company.id, 25, "Applied Through Other Profile")
    session.add_all(
        eligible
        + [
            applied,
            ignored,
            closed,
            unscored,
            inactive_only,
            handled_on_other_profile,
        ]
    )
    session.flush()

    session.add_all(
        [_match(job.id, primary.id, 99 - index) for index, job in enumerate(eligible)]
        + [
            _match(eligible[1].id, inactive.id, 100),
            _match(applied.id, primary.id, 100),
            _match(ignored.id, primary.id, 98),
            _match(closed.id, primary.id, 97),
            _match(inactive_only.id, inactive.id, 96),
            _match(handled_on_other_profile.id, primary.id, 95),
            _match(handled_on_other_profile.id, secondary.id, 90),
            JobUserState(job_id=eligible[0].id, profile_id=primary.id, state="saved"),
            JobUserState(job_id=applied.id, profile_id=primary.id, state="applied"),
            JobUserState(job_id=ignored.id, profile_id=primary.id, state="ignored"),
            JobUserState(
                job_id=handled_on_other_profile.id,
                profile_id=secondary.id,
                state="applied",
            ),
        ]
    )
    session.commit()


def _queue_fragment(response: httpx.Response) -> str:
    return response.text.split('id="apply-today-title"', 1)[1].split(
        'aria-labelledby="strong-matches-title"', 1
    )[0]


def test_default_queue_ranks_ten_open_relevant_unhandled_jobs(tmp_path: Path) -> None:
    application = _app(tmp_path, "m17-default.db")

    async def scenario() -> httpx.Response:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                _seed_queue(session)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                return await client.get("/")

    response = asyncio.run(scenario())
    queue = _queue_fragment(response)

    assert response.status_code == 200
    assert application.state.settings.daily_action_target == 10
    assert 'data-queue-target="10"' in response.text
    assert queue.count("data-queue-rank=") == 10
    assert 'data-metric="apply-today">10<' in response.text
    assert queue.index("Saved Top") < queue.index("Fresh Second")
    assert 'data-queue-rank="1"' in queue
    assert 'data-queue-rank="10"' in queue
    assert "Saved Top" in queue
    assert "Queue Candidate 10" in queue
    assert "Queue Candidate 11" not in queue
    assert "Queue Candidate 12" not in queue
    for excluded_title in (
        "Applied Higher",
        "Ignored Higher",
        "Closed Higher",
        "Unscored Open",
        "Inactive Profile Match",
        "Applied Through Other Profile",
    ):
        assert excluded_title not in queue


def test_configured_target_limits_the_same_ranked_queue(tmp_path: Path) -> None:
    application = _app(tmp_path, "m17-configured.db", target=2)

    async def scenario() -> httpx.Response:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                _seed_queue(session)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                return await client.get("/")

    response = asyncio.run(scenario())
    queue = _queue_fragment(response)

    assert response.status_code == 200
    assert 'data-queue-target="2"' in response.text
    assert 'data-metric="apply-today">2<' in response.text
    assert queue.count("data-queue-rank=") == 2
    assert "Saved Top" in queue
    assert "Fresh Second" in queue
    assert "Queue Candidate 03" not in queue
