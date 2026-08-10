import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.job_user_state import JobUserState
from app.models.jobs import Job
from app.models.notifications import NotificationLog
from app.models.portal_sources import PortalJobSource
from app.models.profiles import CandidateProfile
from app.models.resumes import Resume
from app.models.scan_history import ScanRun, ScanSourceResult
from app.providers.jobs.base import ConnectorJob
from app.services.ai_matching import PARTIAL_SCORING_VERSION, SCORING_VERSION
from app.services.jobs import JobUpsertService
from app.services.notifications import (
    NotificationDestinationService,
    NotificationService,
)
from app.services.portal_discovery import PortalJobCandidate
from app.services.portal_jobs import PortalJobUpsertService


OBSERVED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
PORTAL_SNIPPET = (
    "Build reliable Python services for a customer-facing product while working "
    "with engineering, product, and operations partners across the organization."
)


def _app(
    tmp_path: Path,
    name: str,
    *,
    daily_target: int | None = None,
    portal_query_cap: int | None = None,
):
    seed_path = tmp_path / f"{name}-seed.json"
    seed_path.write_text("[]", encoding="utf-8")
    values: dict[str, object] = {
        "_env_file": None,
        "environment": "test",
        "database_url": f"sqlite:///{(tmp_path / f'{name}.db').as_posix()}",
        "company_seed_path": seed_path,
        "resume_storage_path": tmp_path / f"{name}-resumes",
        "search_provider": "disabled",
        "ai_provider": "disabled",
    }
    if daily_target is not None:
        values["daily_action_target"] = daily_target
    if portal_query_cap is not None:
        values["portal_search_max_queries_per_run"] = portal_query_cap
    return create_app(Settings(**values))


def _profile() -> CandidateProfile:
    return CandidateProfile(
        name="Portal Profile",
        is_active=True,
        years_experience=6,
        target_roles_json=["Backend Engineer", "Mobile Engineer"],
        role_synonyms_json=["Python Engineer"],
        skills_json=["Python", "PostgreSQL"],
        preferred_locations_json=["Bangalore", "Pune"],
        work_modes_json=["Remote"],
        excluded_keywords_json=[],
        notes="",
    )


def _company() -> Company:
    return Company(
        name="Full Co",
        website_url="https://full.example",
        careers_url="https://jobs.full.example",
        provider_type="greenhouse",
        provider_identifier="full",
        discovery_source="seed",
        is_active=True,
        provider_supported=True,
        total_jobs_seen=0,
    )


def _portal_candidate(
    portal: str,
    source_id: str,
    *,
    title: str,
    company: str,
    location: str,
) -> PortalJobCandidate:
    urls = {
        "linkedin": f"https://www.linkedin.com/jobs/view/job-{source_id}",
        "naukri": f"https://www.naukri.com/job-listings-role-{source_id}",
        "indeed": f"https://www.indeed.com/viewjob?jk={source_id}",
    }
    return PortalJobCandidate(
        portal=portal,  # type: ignore[arg-type]
        source_job_id=source_id,
        original_url=urls[portal],
        title=title,
        company_name=company,
        location_text=location,
        snippet=PORTAL_SNIPPET,
    )


def _match(
    job_id: int,
    profile_id: int,
    score: int,
    *,
    partial: bool,
) -> JobMatch:
    return JobMatch(
        job_id=job_id,
        profile_id=profile_id,
        ai_provider="fake",
        ai_model="fixture",
        scoring_version=PARTIAL_SCORING_VERSION if partial else SCORING_VERSION,
        overall_score=score,
        role_score=92,
        skills_score=88,
        experience_score=None if partial else 90,
        location_score=90,
        freshness_score=None if partial else 85,
        seniority_score=None if partial else 86,
        salary_score=None,
        recommendation_label=(
            "Partial / Low Confidence" if partial else "Strong"
        ),
        matching_skills_json=["Python"],
        missing_skills_json=[],
        concerns_json=["Partial data"] if partial else [],
        explanation=(
            "Preliminary fit from explicit portal metadata."
            if partial
            else "Strong fit from the complete job description."
        ),
        source_job_hash=f"{job_id:064d}",
        scored_at=OBSERVED_AT,
    )


def _seed_ui_jobs(session) -> dict[str, int]:
    profile = _profile()
    company = _company()
    session.add_all([profile, company])
    session.commit()

    full = JobUpsertService(session).upsert(
        company.id,
        ConnectorJob(
            source_type="greenhouse",
            source_job_id="full-1",
            title="Backend Engineer",
            location_text="Bangalore",
            description="Build production Python and PostgreSQL services.",
            job_url="https://jobs.full.example/full-1",
        ),
        seen_at=OBSERVED_AT,
    ).job
    PortalJobUpsertService(session).upsert_many(
        [
            _portal_candidate(
                "linkedin",
                "1234567890",
                title="Backend Engineer",
                company="Full Co",
                location="Bangalore",
            ),
            _portal_candidate(
                "indeed",
                "fullindeed1",
                title="Backend Engineer",
                company="Full Co",
                location="Bangalore",
            ),
        ],
        seen_at=OBSERVED_AT,
    )
    partial = PortalJobUpsertService(session).upsert(
        _portal_candidate(
            "linkedin",
            "1234567891",
            title="Mobile Engineer",
            company="Portal Co",
            location="Pune",
        ),
        seen_at=OBSERVED_AT,
    ).job
    unscored = PortalJobUpsertService(session).upsert(
        _portal_candidate(
            "naukri",
            "1234567892",
            title="QA Engineer",
            company="Naukri Co",
            location="Delhi",
        ),
        seen_at=OBSERVED_AT,
    ).job
    session.add_all(
        [
            _match(full.id, profile.id, 88, partial=False),
            _match(partial.id, profile.id, 86, partial=True),
        ]
    )
    session.commit()
    return {
        "profile": profile.id,
        "full": full.id,
        "partial": partial.id,
        "unscored": unscored.id,
    }


def test_portal_filters_list_detail_and_dashboard_presentation(tmp_path: Path) -> None:
    application = _app(tmp_path, "m04-ui")

    async def scenario():
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                ids = _seed_ui_jobs(session)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                return (
                    ids,
                    await client.get("/jobs"),
                    await client.get("/jobs?source=linkedin"),
                    await client.get("/jobs?source=naukri"),
                    await client.get("/jobs?source=greenhouse"),
                    await client.get(f"/jobs/{ids['partial']}"),
                    await client.get(f"/jobs/{ids['full']}"),
                    await client.get("/"),
                )

    (
        ids,
        jobs,
        linkedin,
        naukri,
        greenhouse,
        partial_detail,
        full_detail,
        dashboard,
    ) = asyncio.run(scenario())

    assert all(
        response.status_code == 200
        for response in (
            jobs,
            linkedin,
            naukri,
            greenhouse,
            partial_detail,
            full_detail,
            dashboard,
        )
    )
    for value, label in (
        ("linkedin", "LinkedIn"),
        ("naukri", "Naukri"),
        ("indeed", "Indeed"),
        ("greenhouse", "Greenhouse"),
    ):
        assert f'<option value="{value}"' in jobs.text
        assert f">{label}</option>" in jobs.text

    assert linkedin.text.count(f'data-job-id="{ids["full"]}"') == 1
    assert linkedin.text.count(f'data-job-id="{ids["partial"]}"') == 1
    assert "QA Engineer" not in linkedin.text
    assert "QA Engineer" in naukri.text
    assert "Backend Engineer" in greenhouse.text
    assert f'data-job-id="{ids["partial"]}"' not in greenhouse.text

    assert "Also: Indeed, LinkedIn" in jobs.text
    assert "Partial data" in jobs.text
    assert "Preliminary match · Partial job data" in jobs.text
    assert "Not scored" in jobs.text
    assert "Portal Co" in partial_detail.text
    assert "Job / Portal Co / LinkedIn" in partial_detail.text
    assert "This job was discovered from search-result metadata" in (
        partial_detail.text
    )
    assert "missing requirements were not analyzed" in partial_detail.text
    assert "Search-result snippet" in partial_detail.text
    assert "Preliminary match" in partial_detail.text
    assert "https://www.linkedin.com/jobs/view/job-1234567891" in (
        partial_detail.text
    )

    assert "Job / Full Co / Greenhouse" in full_detail.text
    assert "Original job:" in full_detail.text
    assert "Also found on:" in full_detail.text
    assert "fullindeed1" in full_detail.text
    assert "1234567890" in full_detail.text
    assert "Partial job data" not in full_detail.text
    assert "Strong fit from the complete job description." in full_detail.text

    queue_fragment = dashboard.text.split('id="apply-today-title"', 1)[1].split(
        'aria-labelledby="strong-matches-title"',
        1,
    )[0]
    assert "Portal Co" in queue_fragment
    assert "Preliminary match · Partial job data" in queue_fragment
    assert "Full Co" in queue_fragment


class RecordingSender:
    is_configured = True

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_message(self, _chat_id: str, text: str) -> None:
        self.messages.append(text)


def test_portal_state_application_notifications_and_identity_survive_enrichment(
    tmp_path: Path,
) -> None:
    application = _app(tmp_path, "m04-state")
    sender = RecordingSender()

    async def scenario() -> tuple[int, int, str, httpx.Response]:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                profile = _profile()
                session.add(profile)
                session.commit()
                resume = Resume(
                    profile_id=profile.id,
                    name="Portal Resume",
                    file_path="portal-resume.txt",
                    extracted_text="Python and PostgreSQL experience.",
                    is_primary=True,
                )
                session.add(resume)
                session.commit()
                job = PortalJobUpsertService(session).upsert(
                    _portal_candidate(
                        "linkedin",
                        "1234567893",
                        title="Backend Engineer",
                        company="State Co",
                        location="Bangalore",
                    ),
                    seen_at=OBSERVED_AT,
                ).job
                session.add(_match(job.id, profile.id, 87, partial=True))
                for destination_type, chat_id in (
                    ("recommendation", "-401"),
                    ("application_activity", "-402"),
                ):
                    NotificationDestinationService(session).configure(
                        destination_type,
                        name=destination_type,
                        telegram_chat_id=chat_id,
                        is_enabled=True,
                    )
                job_id = job.id
                profile_id = profile.id
                resume_id = resume.id

            notifications = NotificationService(
                application.state.session_factory,
                sender,
                match_threshold=85,
            )
            application.state.notification_service = notifications
            first_recommendation = await notifications.notify_high_match(
                job_id,
                profile_id,
            )
            assert first_recommendation.sent == 1

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
                with application.state.session_factory() as session:
                    state = session.scalar(select(JobUserState))
                    assert state is not None and state.state == "saved"

                applied = await client.post(
                    f"/jobs/{job_id}/state",
                    data={
                        "profile_id": profile_id,
                        "action": "applied",
                        "resume_id": resume_id,
                        "note": "Applied through LinkedIn.",
                    },
                )
                repeated = await client.post(
                    f"/jobs/{job_id}/state",
                    data={
                        "profile_id": profile_id,
                        "action": "applied",
                        "resume_id": resume_id,
                        "note": "Applied through LinkedIn.",
                    },
                )
                assert applied.status_code == repeated.status_code == 303

                with application.state.session_factory() as session:
                    canonical_id = PortalJobUpsertService(session).upsert(
                        _portal_candidate(
                            "indeed",
                            "stateindeed1",
                            title="Backend Engineer",
                            company="State Co",
                            location="Bangalore",
                        )
                    ).job.id
                    assert canonical_id == job_id
                    duplicate_recommendation = await notifications.notify_high_match(
                        job_id,
                        profile_id,
                    )
                    assert duplicate_recommendation.skipped == 1

                    company = Company(
                        name="State Co",
                        website_url="https://state.example",
                        careers_url="https://jobs.state.example",
                        provider_type="greenhouse",
                        provider_identifier="state",
                        discovery_source="seed",
                        is_active=True,
                        provider_supported=True,
                        total_jobs_seen=0,
                    )
                    session.add(company)
                    session.commit()
                    enriched = JobUpsertService(session).upsert(
                        company.id,
                        ConnectorJob(
                            source_type="greenhouse",
                            source_job_id="state-full",
                            title="Backend Engineer",
                            location_text="Bangalore",
                            description="Complete Backend Engineer description.",
                            job_url="https://jobs.state.example/state-full",
                        ),
                    ).job
                    assert enriched.id == job_id

                enriched_detail = await client.get(
                    f"/jobs/{job_id}?profile_id={profile_id}"
                )
                ignored = await client.post(
                    f"/jobs/{job_id}/state",
                    data={"profile_id": profile_id, "action": "ignored"},
                )
                assert ignored.status_code == 303

            with application.state.session_factory() as session:
                state = session.scalar(select(JobUserState))
                assert state is not None
                assert state.state == "ignored"
                assert state.applied_at is not None
                assert state.resume_id == resume_id
                assert state.note == "Applied through LinkedIn."
                job = session.get(Job, job_id)
                assert job is not None and job.data_completeness == "full"
                assert len(job.portal_sources) == 2
                logs = tuple(session.scalars(select(NotificationLog)))
                assert len(logs) == 2
                assert any(
                    log.event_key == f"high-match:{job_id}:{profile_id}"
                    for log in logs
                )
                assert {log.event_key.split(":", 1)[0] for log in logs} == {
                    "high-match",
                    "application",
                }
            return job_id, profile_id, "Applied through LinkedIn.", enriched_detail

    job_id, profile_id, note, detail = asyncio.run(scenario())

    assert detail.status_code == 200
    assert "Job / State Co / Greenhouse" in detail.text
    assert "State: Applied" in detail.text
    assert "Portal Resume" in detail.text
    assert note in detail.text
    assert "Also found on:" in detail.text
    assert len(sender.messages) == 2
    assert "Preliminary Match — Partial Data / Low Confidence" in sender.messages[0]
    assert "Source: LinkedIn" in sender.messages[0]
    assert "Application recorded" in sender.messages[1]
    assert "Backend Engineer at State Co" in sender.messages[1]
    assert "Source: LinkedIn" in sender.messages[1]


def test_portal_source_results_render_without_company_rows(tmp_path: Path) -> None:
    application = _app(tmp_path, "m04-scans")

    async def scenario() -> httpx.Response:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                run = ScanRun(
                    trigger_type="manual",
                    started_at=OBSERVED_AT,
                    finished_at=OBSERVED_AT,
                    status="partial",
                    companies_checked=0,
                    sources_checked=3,
                    jobs_fetched=12,
                    jobs_new=5,
                    jobs_updated=1,
                    jobs_scored=4,
                    strong_matches=2,
                    errors_count=1,
                    summary="Portal fixture scan.",
                )
                session.add(run)
                session.flush()
                session.add_all(
                    [
                        ScanSourceResult(
                            scan_run_id=run.id,
                            company_id=None,
                            source_type=portal,
                            started_at=OBSERVED_AT,
                            finished_at=OBSERVED_AT,
                            status="failed" if portal == "naukri" else "success",
                            jobs_fetched=count,
                            jobs_new=new,
                            jobs_updated=0,
                            error_message=(
                                "Naukri fixture unavailable"
                                if portal == "naukri"
                                else None
                            ),
                            retry_count=0,
                        )
                        for portal, count, new in (
                            ("linkedin", 7, 3),
                            ("naukri", 0, 0),
                            ("indeed", 5, 2),
                        )
                    ]
                )
                session.commit()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                return await client.get("/scans")

    page = asyncio.run(scenario())

    assert page.status_code == 200
    assert "Source activity" in page.text
    for source, label in (
        ("linkedin", "LinkedIn"),
        ("naukri", "Naukri"),
        ("indeed", "Indeed"),
    ):
        assert f'data-source-type="{source}"' in page.text
        assert label in page.text
    assert page.text.count("Non-company source") == 3
    assert "Naukri fixture unavailable" in page.text


async def _download_backup(application) -> bytes:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/settings/backup/export")
    assert response.status_code == 200
    return response.content


def test_v2_backup_round_trip_preserves_portals_completeness_state_and_settings(
    tmp_path: Path,
) -> None:
    source = _app(tmp_path, "m04-backup-source", daily_target=14, portal_query_cap=12)

    async def create_archive() -> bytes:
        async with source.router.lifespan_context(source):
            with source.state.session_factory() as session:
                ids = _seed_ui_jobs(session)
                session.add(
                    JobUserState(
                        job_id=ids["partial"],
                        profile_id=ids["profile"],
                        state="saved",
                        note="Preserve portal state",
                        updated_at=OBSERVED_AT,
                    )
                )
                destination = NotificationDestinationService(session).configure(
                    "recommendation",
                    name="Portal recommendations",
                    telegram_chat_id="-499",
                    is_enabled=True,
                )
                session.add(
                    NotificationLog(
                        destination_id=destination.id,
                        job_id=ids["partial"],
                        event_key=(
                            f"high-match:{ids['partial']}:{ids['profile']}"
                        ),
                        status="sent",
                        sent_at=OBSERVED_AT,
                    )
                )
                session.commit()
            return await _download_backup(source)

    archive = asyncio.run(create_archive())
    target = _app(tmp_path, "m04-backup-target")

    async def restore_archive() -> httpx.Response:
        async with target.router.lifespan_context(target):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=target),
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                return await client.post(
                    "/settings/backup/restore",
                    data={"confirm": "replace"},
                    files={
                        "backup_file": (
                            "job-agent-backup.zip",
                            archive,
                            "application/zip",
                        )
                    },
                )

    response = asyncio.run(restore_archive())
    assert response.status_code == 303, response.text
    assert target.state.settings.daily_action_target == 14
    assert target.state.settings.portal_search_max_queries_per_run == 12

    restarted = _app(tmp_path, "m04-backup-target")

    async def verify_restored() -> None:
        async with restarted.router.lifespan_context(restarted):
            with restarted.state.session_factory() as session:
                jobs = tuple(session.scalars(select(Job).order_by(Job.id)))
                observations = tuple(
                    session.scalars(select(PortalJobSource).order_by(PortalJobSource.id))
                )
                state = session.scalar(select(JobUserState))
                assert len(jobs) == 3
                assert {job.data_completeness for job in jobs} == {"full", "partial"}
                assert len(observations) == 4
                assert {item.portal_name for item in observations} == {
                    "linkedin",
                    "indeed",
                    "naukri",
                }
                assert state is not None
                assert state.state == "saved"
                assert state.note == "Preserve portal state"
                assert session.scalar(select(func.count(JobMatch.id))) == 2
                assert session.scalar(select(func.count(NotificationLog.id))) == 1
                assert restarted.state.settings.daily_action_target == 14
                assert (
                    restarted.state.settings.portal_search_max_queries_per_run == 12
                )

    asyncio.run(verify_restored())
