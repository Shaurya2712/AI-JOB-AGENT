import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import httpx
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.job_user_state import JobUserState
from app.models.jobs import Job
from app.models.notifications import NotificationLog
from app.models.profiles import CandidateProfile
from app.models.resumes import Resume
from app.models.scan_history import ScanRun, ScanSourceResult
from app.providers.ai.base import AIProvider, AIProviderRequest
from app.providers.jobs.base import ConnectorJob, JobConnector
from app.providers.search.base import WebSearchProvider, WebSearchResult
from app.schemas.ai import AIMatchOutput
from app.services.companies import CompanyService
from app.services.job_qualification import qualify_job
from app.services.notifications import (
    NotificationDestinationService,
    NotificationService,
)
from app.services.scan_history import ScanHistoryService
from app.services.scans import ApplicationScanPipeline, ScanController
import app.services.scans as scan_services


SOURCE_TELEGRAM_SECRET = "m23-source-telegram-secret"
SOURCE_AI_SECRET = "m23-source-ai-secret"
TARGET_TELEGRAM_SECRET = "m23-target-telegram-secret"
SUPPORTED_SOURCES = ("greenhouse", "lever", "ashby", "workday")
ALL_SOURCES = (*SUPPORTED_SOURCES, "custom")


def _application(
    tmp_path: Path,
    name: str,
    *,
    source_settings: bool = False,
):
    seed_path = tmp_path / f"{name}-seeds.json"
    seed_path.write_text("[]", encoding="utf-8")
    values: dict[str, object] = {
        "environment": "test",
        "database_url": f"sqlite:///{(tmp_path / f'{name}.db').as_posix()}",
        "log_level": "WARNING",
        "company_seed_path": seed_path,
        "resume_storage_path": tmp_path / f"{name}-resumes",
        "search_provider": "disabled",
        "ai_provider": "disabled",
        "telegram_bot_token": (
            SOURCE_TELEGRAM_SECRET
            if source_settings
            else TARGET_TELEGRAM_SECRET
        ),
    }
    if source_settings:
        values.update(
            {
                "daily_action_target": 3,
                "scan_interval_hours": 6,
                "openai_api_key": SOURCE_AI_SECRET,
            }
        )
    return create_app(Settings(**values)), seed_path


def _write_supported_seeds(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "name": "Greenhouse Co",
                    "website_url": "https://greenhouse.example",
                    "careers_url": "https://boards.greenhouse.io/greenhouse-co",
                    "provider_type": "greenhouse",
                    "provider_identifier": "greenhouse-co",
                    "provider_supported": True,
                },
                {
                    "name": "Lever Co",
                    "website_url": "https://lever.example",
                    "careers_url": "https://jobs.lever.co/lever-co",
                    "provider_type": "lever",
                    "provider_identifier": "lever-co",
                    "provider_supported": True,
                },
                {
                    "name": "Ashby Co",
                    "website_url": "https://ashby.example",
                    "careers_url": "https://jobs.ashbyhq.com/ashby-co",
                    "provider_type": "ashby",
                    "provider_identifier": "ashby-co",
                    "provider_supported": True,
                },
                {
                    "name": "Workday Co",
                    "website_url": "https://workday.example",
                    "careers_url": "https://acme.wd5.myworkdayjobs.com/External",
                    "provider_type": "workday",
                    "provider_identifier": (
                        "acme.wd5.myworkdayjobs.com/acme/External"
                    ),
                    "provider_supported": True,
                },
            ]
        ),
        encoding="utf-8",
    )


class FixtureSearchProvider(WebSearchProvider):
    name = "fixture"

    def __init__(self) -> None:
        self.queries: list[str] = []

    @property
    def is_configured(self) -> bool:
        return True

    async def search(self, query: str) -> list[WebSearchResult]:
        self.queries.append(query)
        return [
            WebSearchResult(
                title="Custom Co Careers",
                url="https://custom.example/careers?utm_source=fixture",
                description="Open jobs and careers at Custom Co",
            )
        ]


class FixtureSourceCatalog:
    def __init__(self) -> None:
        self.scan_number = 0
        self.fetches: list[tuple[int, str, str]] = []

    def begin_scan(self) -> None:
        self.scan_number += 1

    def jobs_for(
        self,
        source_type: str,
        provider_identifier: str,
    ) -> list[ConnectorJob]:
        self.fetches.append(
            (self.scan_number, source_type, provider_identifier)
        )
        if source_type == "greenhouse" and self.scan_number >= 4:
            return []

        description = "Build reliable Python services. 5 years experience required."
        if source_type == "greenhouse" and self.scan_number == 3:
            description = (
                "Build changed Python platform services and APIs. "
                "5 years experience required."
            )
        jobs = [
            ConnectorJob(
                source_type=source_type,
                source_job_id=f"{source_type}-backend-1",
                title="Senior Backend Engineer",
                location_text="Remote, India",
                description=description,
                job_url=(
                    f"https://jobs.example/{source_type}/backend-1"
                    "?utm_source=m23"
                ),
            )
        ]
        if source_type == "custom":
            jobs.append(
                ConnectorJob(
                    source_type="custom",
                    source_job_id="custom-intern-1",
                    title="Backend Engineering Intern",
                    location_text="Remote, India",
                    description="A short internship building Python tools.",
                    job_url="https://custom.example/jobs/intern-1",
                )
            )
        return jobs


class FixtureConnector(JobConnector):
    def __init__(self, source_type: str, catalog: FixtureSourceCatalog) -> None:
        self.source_type = source_type
        self.catalog = catalog

    async def fetch_open_jobs(
        self,
        provider_identifier: str,
    ) -> list[ConnectorJob]:
        return self.catalog.jobs_for(self.source_type, provider_identifier)


class FixtureAIProvider(AIProvider):
    name = "fixture"
    model = "m23-structured-v1"

    def __init__(self, resume_id: int) -> None:
        self.resume_id = resume_id
        self.requests: list[AIProviderRequest] = []

    @property
    def is_configured(self) -> bool:
        return True

    async def score_match(self, request: AIProviderRequest) -> AIMatchOutput:
        self.requests.append(request)
        changed = "changed Python platform" in request.user_prompt
        score = 95 if changed else 90
        return AIMatchOutput(
            overall_score=score,
            role_score=95,
            skills_score=90,
            experience_score=92,
            location_score=95,
            freshness_score=90,
            seniority_score=88,
            salary_score=None,
            matching_skills=["Python"],
            missing_skills=[],
            concerns=[],
            explanation="Strong deterministic M23 fixture match.",
            suggested_resume_id=self.resume_id,
            profile_suggestions=[],
        )


class FixtureTelegramSender:
    is_configured = True

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send_message(self, chat_id: str, text: str) -> None:
        self.messages.append((chat_id, text))


def _connector_opener(
    source_type: str,
    catalog: FixtureSourceCatalog,
):
    @asynccontextmanager
    async def opener(_settings):
        if source_type == "greenhouse":
            catalog.begin_scan()
        yield FixtureConnector(source_type, catalog)

    return opener


def _install_external_fixtures(
    monkeypatch,
    search_provider: FixtureSearchProvider,
    catalog: FixtureSourceCatalog,
    ai_provider: FixtureAIProvider,
) -> None:
    @asynccontextmanager
    async def open_search(_settings):
        yield search_provider

    @asynccontextmanager
    async def open_ai(_settings):
        yield ai_provider

    monkeypatch.setattr(scan_services, "open_search_provider", open_search)
    monkeypatch.setattr(scan_services, "open_ai_provider", open_ai)
    for attribute, source_type in (
        ("open_greenhouse_connector", "greenhouse"),
        ("open_lever_connector", "lever"),
        ("open_ashby_connector", "ashby"),
        ("open_workday_connector", "workday"),
        ("open_generic_career_page_connector", "custom"),
    ):
        monkeypatch.setattr(
            scan_services,
            attribute,
            _connector_opener(source_type, catalog),
        )


def _configure_destinations(application) -> None:
    with application.state.session_factory() as session:
        service = NotificationDestinationService(session)
        for destination_type, chat_id in (
            ("recommendation", "-23001"),
            ("application_activity", "-23002"),
            ("scan_summary", "-23003"),
        ):
            service.configure(
                destination_type,
                name=f"M23 {destination_type}",
                telegram_chat_id=chat_id,
                is_enabled=True,
            )


async def _run_scan(controller: ScanController):
    assert await controller.start_manual() is True
    snapshot = await controller.wait_for_idle()
    assert snapshot.status == "success"
    return snapshot


def test_frozen_v1_end_to_end_workflow(tmp_path: Path, monkeypatch) -> None:
    source, source_seed_path = _application(
        tmp_path,
        "m23-source",
        source_settings=True,
    )

    async def workflow() -> None:
        async with source.router.lifespan_context(source):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=source),
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                # 1. Create profile.
                profile_response = await client.post(
                    "/profiles",
                    data={
                        "name": "M23 Backend Profile",
                        "is_active": "on",
                        "years_experience": "6",
                        "target_roles": "Backend Engineer\nSoftware Engineer",
                        "role_synonyms": "Python Engineer",
                        "skills": "Python\nSQL",
                        "preferred_locations": "India\nRemote",
                        "work_modes": ["Remote", "Hybrid"],
                        "minimum_salary": "1500000",
                        "salary_currency": "INR",
                        "excluded_keywords": "Internship",
                        "notes": "Prefer product teams.",
                    },
                )
                assert profile_response.status_code == 303
                with source.state.session_factory() as session:
                    profile = session.scalar(select(CandidateProfile))
                    assert profile is not None
                    profile_id = profile.id

                # 2. Add resume through the browser workflow.
                resume_response = await client.post(
                    f"/profiles/{profile_id}/resumes",
                    data={"resume_name": "M23 Python Resume", "make_primary": "on"},
                    files={
                        "resume_file": (
                            "resume.txt",
                            b"Backend engineer with Python, SQL, and API experience.",
                            "text/plain",
                        )
                    },
                )
                assert resume_response.status_code == 303
                with source.state.session_factory() as session:
                    resume = session.scalar(select(Resume))
                    assert resume is not None
                    assert "Python, SQL" in resume.extracted_text
                    resume_id = resume.id
                    resume_reference = resume.file_path

                # 3. Load the four supported ATS seeds and verify idempotency.
                _write_supported_seeds(source_seed_path)
                with source.state.session_factory() as session:
                    first_seed = CompanyService(session).import_seed_file(
                        source_seed_path
                    )
                    second_seed = CompanyService(session).import_seed_file(
                        source_seed_path
                    )
                assert (first_seed.created, first_seed.existing) == (4, 0)
                assert (second_seed.created, second_seed.existing) == (0, 4)

                search_provider = FixtureSearchProvider()
                catalog = FixtureSourceCatalog()
                ai_provider = FixtureAIProvider(resume_id)
                telegram_sender = FixtureTelegramSender()
                _install_external_fixtures(
                    monkeypatch,
                    search_provider,
                    catalog,
                    ai_provider,
                )
                _configure_destinations(source)
                notifications = NotificationService(
                    source.state.session_factory,
                    telegram_sender,
                    match_threshold=85,
                )
                source.state.notification_service = notifications
                controller = ScanController(
                    ApplicationScanPipeline(
                        source.state.session_factory,
                        source.state.settings,
                        recommendation_notifier=notifications,
                    ),
                    completion_notifier=notifications,
                    history_writer=ScanHistoryService(source.state.session_factory),
                )
                source.state.scan_controller = controller

                # 4-10. Discovery, ATS detection, every connector, normalization,
                # dedupe, lifecycle, qualification, and structured AI scoring.
                search_response = await client.post("/scans/search-now")
                assert search_response.status_code == 303
                assert search_response.headers["location"] == "/?scan=started"
                first_scan = await controller.wait_for_idle()
                assert first_scan.status == "success"
                assert (
                    first_scan.companies_checked,
                    first_scan.sources_checked,
                    first_scan.jobs_fetched,
                    first_scan.jobs_new,
                    first_scan.jobs_scored,
                ) == (5, 5, 6, 6, 5)
                assert search_provider.queries
                assert {
                    source_type
                    for scan_number, source_type, _identifier in catalog.fetches
                    if scan_number == 1
                } == set(ALL_SOURCES)

                with source.state.session_factory() as session:
                    companies = tuple(session.scalars(select(Company)))
                    jobs = tuple(session.scalars(select(Job).order_by(Job.id)))
                    matches = tuple(session.scalars(select(JobMatch)))
                    assert len(companies) == 5
                    assert {
                        company.provider_type for company in companies
                    } == set(ALL_SOURCES)
                    assert len(jobs) == 6
                    assert len(matches) == 5
                    internship = next(
                        job for job in jobs if "Intern" in job.title
                    )
                    assert qualify_job(profile, internship).qualified is False
                    greenhouse_job = next(
                        job for job in jobs if job.source_type == "greenhouse"
                    )
                    assert qualify_job(profile, greenhouse_job).qualified is True
                    greenhouse_job_id = greenhouse_job.id
                    original_match = next(
                        match
                        for match in matches
                        if match.job_id == greenhouse_job_id
                    )
                    original_match_id = original_match.id
                    original_source_hash = original_match.source_job_hash

                # 11-12. Dashboard/filter views and configured daily queue.
                dashboard = await client.get("/")
                strong_jobs = await client.get(
                    f"/jobs?profile_id={profile_id}&min_score=85&lifecycle=open"
                )
                detail = await client.get(
                    f"/jobs/{greenhouse_job_id}?profile_id={profile_id}"
                )
                assert dashboard.status_code == strong_jobs.status_code == 200
                assert detail.status_code == 200
                assert 'data-queue-target="3"' in dashboard.text
                assert dashboard.text.count("data-queue-rank=") == 3
                assert 'data-metric="strong-matches">5<' in dashboard.text
                assert "5 jobs" in strong_jobs.text
                assert "M23 Python Resume" in detail.text

                # 13-15. Save, mark Applied with resume/note, and retain history.
                saved = await client.post(
                    f"/jobs/{greenhouse_job_id}/state",
                    data={"profile_id": profile_id, "action": "saved"},
                )
                assert saved.status_code == 303
                applied = await client.post(
                    f"/jobs/{greenhouse_job_id}/state",
                    data={
                        "profile_id": profile_id,
                        "action": "applied",
                        "resume_id": resume_id,
                        "note": "Applied during M23 verification.",
                    },
                )
                assert applied.status_code == 303
                with source.state.session_factory() as session:
                    state = session.scalar(select(JobUserState))
                    assert state is not None
                    assert state.state == "applied"
                    assert state.resume_id == resume_id
                    assert state.applied_at is not None
                    assert state.note == "Applied during M23 verification."

                # 16. A second scan keeps one row per job and skips rescoring.
                second_scan = await _run_scan(controller)
                assert (second_scan.jobs_new, second_scan.jobs_updated) == (0, 0)
                assert second_scan.jobs_scored == 0
                assert len(ai_provider.requests) == 5
                with source.state.session_factory() as session:
                    assert session.scalar(select(func.count(Job.id))) == 6
                    assert session.scalar(select(func.count(JobMatch.id))) == 5
                    state = session.scalar(select(JobUserState))
                    assert state is not None and state.state == "applied"

                # 17. A material description change updates and rescored one row.
                third_scan = await _run_scan(controller)
                assert (third_scan.jobs_new, third_scan.jobs_updated) == (0, 1)
                assert third_scan.jobs_scored == 1
                assert len(ai_provider.requests) == 6
                with source.state.session_factory() as session:
                    changed_match = session.scalar(
                        select(JobMatch).where(
                            JobMatch.job_id == greenhouse_job_id
                        )
                    )
                    assert changed_match is not None
                    assert changed_match.id == original_match_id
                    assert changed_match.overall_score == 95
                    assert changed_match.source_job_hash != original_source_hash

                # 18. Repeated successful disappearance safely closes the job.
                fourth_scan = await _run_scan(controller)
                with source.state.session_factory() as session:
                    missing_once = session.get(Job, greenhouse_job_id)
                    assert missing_once is not None
                    assert (
                        missing_once.lifecycle_status,
                        missing_once.consecutive_missing_scans,
                    ) == ("open", 1)
                fifth_scan = await _run_scan(controller)
                with source.state.session_factory() as session:
                    missing_twice = session.get(Job, greenhouse_job_id)
                    assert missing_twice is not None
                    assert (
                        missing_twice.lifecycle_status,
                        missing_twice.consecutive_missing_scans,
                    ) == ("possibly_closed", 2)
                sixth_scan = await _run_scan(controller)
                with source.state.session_factory() as session:
                    closed = session.get(Job, greenhouse_job_id)
                    state = session.scalar(select(JobUserState))
                    assert closed is not None
                    assert (
                        closed.lifecycle_status,
                        closed.consecutive_missing_scans,
                    ) == ("closed", 3)
                    assert state is not None and state.state == "applied"
                    assert session.scalar(select(func.count(ScanRun.id))) == 6
                    assert session.scalar(
                        select(func.count(ScanSourceResult.id))
                    ) == 30
                assert all(
                    scan.errors_count == 0
                    for scan in (fourth_scan, fifth_scan, sixth_scan)
                )

                # 19. Recommendation, application, and summary Telegram paths.
                duplicate = await notifications.notify_high_match(
                    greenhouse_job_id,
                    profile_id,
                )
                assert duplicate.skipped == 1
                with source.state.session_factory() as session:
                    logs = tuple(
                        session.scalars(
                            select(NotificationLog).order_by(NotificationLog.id)
                        )
                    )
                    assert len(logs) == 12
                    assert all(log.status == "sent" for log in logs)
                    assert {
                        log.event_key.split(":", 1)[0] for log in logs
                    } == {"high-match", "application", "scan-summary"}
                assert {chat_id for chat_id, _text in telegram_sender.messages} == {
                    "-23001",
                    "-23002",
                    "-23003",
                }
                assert len(telegram_sender.messages) == 12

                scan_page = await client.get("/scans")
                assert scan_page.status_code == 200
                assert "Run history" in scan_page.text

                # 20. Export the complete workflow state as one backup.
                backup_response = await client.post("/settings/backup/export")
                assert backup_response.status_code == 200
                backup_bytes = backup_response.content
                with ZipFile(BytesIO(backup_bytes)) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    assert manifest["settings"]["daily_action_target"] == 3
                    assert manifest["settings"]["scan_interval_hours"] == 6
                    assert "telegram_bot_token" not in manifest["settings"]
                    assert "openai_api_key" not in manifest["settings"]
                    assert f"resumes/{resume_reference}" in archive.namelist()

        target, _target_seed_path = _application(tmp_path, "m23-target")
        async with target.router.lifespan_context(target):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=target),
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                restored = await client.post(
                    "/settings/backup/restore",
                    data={"confirm": "replace"},
                    files={
                        "backup_file": (
                            "m23-backup.zip",
                            backup_bytes,
                            "application/zip",
                        )
                    },
                )
                assert restored.status_code == 303
            assert target.state.settings.daily_action_target == 3
            assert target.state.settings.scan_interval_hours == 6
            target_secret = target.state.settings.telegram_bot_token
            assert target_secret is not None
            assert target_secret.get_secret_value() == TARGET_TELEGRAM_SECRET

        # 21. Restart over the restored database and confirm durable settings,
        # scheduler configuration, local path precedence, and workflow state.
        restarted, _restart_seed_path = _application(tmp_path, "m23-target")
        async with restarted.router.lifespan_context(restarted):
            assert restarted.state.settings.daily_action_target == 3
            assert restarted.state.settings.scan_interval_hours == 6
            schedule = restarted.state.scan_scheduler.snapshot()
            assert schedule.interval_hours == 6
            assert schedule.next_run_at is not None
            restart_secret = restarted.state.settings.telegram_bot_token
            assert restart_secret is not None
            assert restart_secret.get_secret_value() == TARGET_TELEGRAM_SECRET
            with restarted.state.session_factory() as session:
                restored_profile = session.scalar(select(CandidateProfile))
                restored_resume = session.scalar(select(Resume))
                restored_state = session.scalar(select(JobUserState))
                restored_job = session.get(Job, greenhouse_job_id)
                assert restored_profile is not None
                assert restored_profile.name == "M23 Backend Profile"
                assert restored_resume is not None
                assert restored_resume.extracted_text.startswith("Backend engineer")
                assert restored_state is not None
                assert restored_state.state == "applied"
                assert restored_job is not None
                assert restored_job.lifecycle_status == "closed"
                assert session.scalar(select(func.count(Job.id))) == 6
                assert session.scalar(select(func.count(JobMatch.id))) == 5
                assert session.scalar(select(func.count(ScanRun.id))) == 6
                assert session.scalar(select(func.count(NotificationLog.id))) == 12
            restored_file = (
                restarted.state.settings.resume_storage_path / resume_reference
            )
            assert restored_file.read_bytes().startswith(b"Backend engineer")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=restarted),
                base_url="http://testserver",
            ) as client:
                health, dashboard, jobs, scans = await asyncio.gather(
                    client.get("/health"),
                    client.get("/"),
                    client.get("/jobs?lifecycle=all"),
                    client.get("/scans"),
                )
            assert health.json() == {"status": "ok", "database": "ok"}
            assert all(
                response.status_code == 200
                for response in (dashboard, jobs, scans)
            )
            assert 'data-queue-target="3"' in dashboard.text
            assert "M23 Backend Profile" in jobs.text
            assert "Run history" in scans.text

    asyncio.run(workflow())
