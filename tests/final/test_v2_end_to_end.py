import asyncio
from contextlib import asynccontextmanager
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
from app.providers.ai.base import AIProvider, AIProviderRequest
from app.providers.jobs.base import ConnectorJob, JobConnector
from app.providers.search.base import (
    SearchProviderError,
    WebSearchProvider,
    WebSearchResult,
)
from app.schemas.ai import AIMatchOutput
from app.services.ai_matching import PARTIAL_SCORING_VERSION, SCORING_VERSION
from app.services.notifications import (
    NotificationDestinationService,
    NotificationService,
)
from app.services.scan_history import ScanHistoryService
from app.services.scans import ApplicationScanPipeline, ScanController
import app.services.scans as scan_services


USEFUL_SNIPPET = (
    "Build reliable Python services and customer-facing products while working "
    "with engineering, product, and operations partners across the organization."
)


def _application(tmp_path: Path, name: str):
    seed_path = tmp_path / f"{name}-seeds.json"
    seed_path.write_text("[]", encoding="utf-8")
    return create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=f"sqlite:///{(tmp_path / f'{name}.db').as_posix()}",
            company_seed_path=seed_path,
            resume_storage_path=tmp_path / f"{name}-resumes",
            search_provider="disabled",
            ai_provider="disabled",
            portal_search_max_queries_per_run=3,
            scan_interval_hours=6,
        )
    )


def _company(
    name: str,
    source_type: str,
    identifier: str,
    careers_url: str,
) -> Company:
    return Company(
        name=name,
        website_url=f"https://{identifier.split('/')[0]}.example",
        careers_url=careers_url,
        provider_type=source_type,
        provider_identifier=identifier,
        discovery_source="v2-final-fixture",
        is_active=True,
        provider_supported=True,
        total_jobs_seen=0,
    )


class FixtureCatalog:
    def __init__(self) -> None:
        self.scan_number = 0

    def begin_scan(self) -> None:
        self.scan_number += 1

    def jobs_for(self, source_type: str, identifier: str) -> list[ConnectorJob]:
        if source_type == "greenhouse":
            if identifier == "acme":
                return [
                    _connector_job(
                        "greenhouse",
                        "acme-backend",
                        "Backend Engineer",
                        "Bangalore",
                        "https://boards.greenhouse.io/acme/jobs/acme-backend",
                    )
                ]
            if identifier == "enrich":
                if self.scan_number < 2:
                    return []
                return [
                    _connector_job(
                        "greenhouse",
                        "enrich-platform",
                        "Platform Engineer",
                        "Pune",
                        "https://boards.greenhouse.io/enrich/jobs/enrich-platform",
                    )
                ]
            if identifier == "ambiguous":
                return [
                    _connector_job(
                        "greenhouse",
                        "ambiguous-a",
                        "Data Engineer",
                        "Chennai",
                        "https://boards.greenhouse.io/ambiguous/jobs/a",
                        description="First distinct Python data requisition.",
                    ),
                    _connector_job(
                        "greenhouse",
                        "ambiguous-b",
                        "Data Engineer",
                        "Chennai",
                        "https://boards.greenhouse.io/ambiguous/jobs/b",
                        description="Second distinct Python data requisition.",
                    ),
                ]

        title = "Backend Engineer"
        location = "Remote, India"
        return [
            _connector_job(
                source_type,
                f"{source_type}-backend",
                title,
                location,
                f"https://jobs.example/{source_type}/backend",
            )
        ]


def _connector_job(
    source_type: str,
    source_job_id: str,
    title: str,
    location: str,
    url: str,
    *,
    description: str = (
        "Build production Python services from a complete job description. "
        "Five years of engineering experience required."
    ),
) -> ConnectorJob:
    return ConnectorJob(
        source_type=source_type,
        source_job_id=source_job_id,
        title=title,
        location_text=location,
        description=description,
        job_url=url,
    )


class FixtureConnector(JobConnector):
    def __init__(self, source_type: str, catalog: FixtureCatalog) -> None:
        self.source_type = source_type
        self.catalog = catalog

    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        return self.catalog.jobs_for(self.source_type, provider_identifier)


class FixtureSearchProvider(WebSearchProvider):
    name = "v2-final-search"

    def __init__(self, catalog: FixtureCatalog) -> None:
        self.catalog = catalog
        self.queries: list[str] = []

    @property
    def is_configured(self) -> bool:
        return True

    async def search(self, query: str) -> list[WebSearchResult]:
        self.queries.append(query)
        await asyncio.sleep(0.005)
        if "site:linkedin.com/jobs/view" in query:
            if self.catalog.scan_number >= 2:
                raise SearchProviderError("LinkedIn final-fixture failure")
            return [
                WebSearchResult(
                    title="Backend Engineer at Acme in Bangalore",
                    url="https://www.linkedin.com/jobs/view/backend-4100000001",
                    description=USEFUL_SNIPPET,
                ),
                WebSearchResult(
                    title="Platform Engineer at Enrich in Pune",
                    url="https://www.linkedin.com/jobs/view/platform-4100000002",
                    description=USEFUL_SNIPPET,
                ),
            ]
        if "site:naukri.com/job-listings" in query:
            return [
                WebSearchResult(
                    title="Mobile Engineer job at Naukri Co in Hyderabad",
                    url=(
                        "https://www.naukri.com/"
                        "job-listings-mobile-naukri-hyderabad-5100000001"
                    ),
                    description=USEFUL_SNIPPET,
                ),
                WebSearchResult(
                    title="QA Engineer job at Sparse Co in Delhi",
                    url=(
                        "https://www.naukri.com/"
                        "job-listings-qa-sparse-delhi-5100000002"
                    ),
                    description="Apply now.",
                ),
                WebSearchResult(
                    title="Data Engineer job at Ambiguous Co in Chennai",
                    url=(
                        "https://www.naukri.com/"
                        "job-listings-data-ambiguous-chennai-5100000003"
                    ),
                    description=USEFUL_SNIPPET,
                ),
            ]
        if "site:indeed.com/viewjob" in query:
            return [
                WebSearchResult(
                    title="Backend Engineer at Acme in Bangalore",
                    url="https://www.indeed.com/viewjob?jk=indeed4100001",
                    description=USEFUL_SNIPPET,
                )
            ]
        return []


class FixtureAIProvider(AIProvider):
    name = "v2-final-ai"
    model = "fixture-v1"

    def __init__(self) -> None:
        self.requests: list[AIProviderRequest] = []

    @property
    def is_configured(self) -> bool:
        return True

    async def score_match(self, request: AIProviderRequest) -> AIMatchOutput:
        self.requests.append(request)
        partial = '"data_completeness":"partial"' in request.user_prompt
        return AIMatchOutput(
            overall_score=93 if partial else 92,
            role_score=94,
            skills_score=90,
            experience_score=None if partial else 90,
            location_score=91,
            freshness_score=None if partial else 86,
            seniority_score=None if partial else 88,
            salary_score=None,
            matching_skills=["Python"],
            missing_skills=[],
            concerns=["Only portal metadata is available"] if partial else [],
            explanation=(
                "Preliminary fit using only explicit portal metadata."
                if partial
                else "Authoritative fit using the complete job description."
            ),
            suggested_resume_id=None,
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
    catalog: FixtureCatalog,
):
    @asynccontextmanager
    async def opener(_settings):
        if source_type == "greenhouse":
            catalog.begin_scan()
        yield FixtureConnector(source_type, catalog)

    return opener


def _install_fixtures(
    monkeypatch,
    search_provider: FixtureSearchProvider,
    catalog: FixtureCatalog,
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


def _configure_companies(application) -> None:
    with application.state.session_factory() as session:
        session.add_all(
            [
                _company(
                    "Acme",
                    "greenhouse",
                    "acme",
                    "https://boards.greenhouse.io/acme",
                ),
                _company(
                    "Enrich",
                    "greenhouse",
                    "enrich",
                    "https://boards.greenhouse.io/enrich",
                ),
                _company(
                    "Ambiguous Co",
                    "greenhouse",
                    "ambiguous",
                    "https://boards.greenhouse.io/ambiguous",
                ),
                _company(
                    "Lever Co",
                    "lever",
                    "lever",
                    "https://jobs.lever.co/lever",
                ),
                _company(
                    "Ashby Co",
                    "ashby",
                    "ashby",
                    "https://jobs.ashbyhq.com/ashby",
                ),
                _company(
                    "Workday Co",
                    "workday",
                    "acme.wd5.myworkdayjobs.com/acme/External",
                    "https://acme.wd5.myworkdayjobs.com/External",
                ),
            ]
        )
        session.commit()


def _configure_notifications(application) -> None:
    with application.state.session_factory() as session:
        service = NotificationDestinationService(session)
        for destination_type, chat_id in (
            ("recommendation", "-501"),
            ("application_activity", "-502"),
            ("scan_summary", "-503"),
        ):
            service.configure(
                destination_type,
                name=f"V2 final {destination_type}",
                telegram_chat_id=chat_id,
                is_enabled=True,
            )


def test_v2_realistic_integrated_workflow(tmp_path: Path, monkeypatch) -> None:
    application = _application(tmp_path, "v2-final")

    async def workflow() -> None:
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                profile_response = await client.post(
                    "/profiles",
                    data={
                        "name": "V2 Final Profile",
                        "is_active": "on",
                        "years_experience": "6",
                        "target_roles": (
                            "Backend Engineer\nPlatform Engineer\nMobile Engineer\n"
                            "Data Engineer\nQA Engineer"
                        ),
                        "role_synonyms": "Python Engineer",
                        "skills": "Python\nSQL",
                        "preferred_locations": (
                            "Bangalore\nPune\nHyderabad\nChennai\nDelhi"
                        ),
                        "work_modes": ["Remote"],
                        "excluded_keywords": "Internship",
                        "notes": "V2 deterministic final verification.",
                    },
                )
                assert profile_response.status_code == 303
                with application.state.session_factory() as session:
                    profile = session.scalar(
                        select(CandidateProfile).where(
                            CandidateProfile.name == "V2 Final Profile"
                        )
                    )
                    assert profile is not None
                    profile_id = profile.id
                    applied_profile = CandidateProfile(
                        name="V2 Applied State Profile",
                        is_active=False,
                        years_experience=6,
                        target_roles_json=["Platform Engineer"],
                        role_synonyms_json=[],
                        skills_json=["Python"],
                        preferred_locations_json=["Pune"],
                        work_modes_json=[],
                        excluded_keywords_json=[],
                        notes="",
                    )
                    session.add(applied_profile)
                    session.flush()
                    resume = Resume(
                        profile_id=applied_profile.id,
                        name="V2 Applied Resume",
                        file_path="v2-applied-resume.txt",
                        extracted_text="Six years building Python platforms.",
                        is_primary=True,
                    )
                    session.add(resume)
                    session.commit()
                    applied_profile_id = applied_profile.id
                    resume_id = resume.id

                _configure_companies(application)
                catalog = FixtureCatalog()
                search_provider = FixtureSearchProvider(catalog)
                ai_provider = FixtureAIProvider()
                telegram_sender = FixtureTelegramSender()
                _install_fixtures(
                    monkeypatch,
                    search_provider,
                    catalog,
                    ai_provider,
                )
                _configure_notifications(application)
                notifications = NotificationService(
                    application.state.session_factory,
                    telegram_sender,
                    match_threshold=85,
                )
                application.state.notification_service = notifications
                controller = ScanController(
                    ApplicationScanPipeline(
                        application.state.session_factory,
                        application.state.settings,
                        recommendation_notifier=notifications,
                    ),
                    completion_notifier=notifications,
                    history_writer=ScanHistoryService(
                        application.state.session_factory
                    ),
                )
                application.state.scan_controller = controller

                first_start = await client.post("/scans/search-now")
                assert first_start.status_code == 303
                assert await controller.start_manual() is False
                first_scan = await controller.wait_for_idle()
                assert first_scan.status == "success"
                assert first_scan.errors_count == 0

                with application.state.session_factory() as session:
                    assert session.scalar(select(func.count(Job.id))) == 10
                    assert session.scalar(
                        select(func.count(PortalJobSource.id))
                    ) == 6
                    acme_job = session.scalar(
                        select(Job).where(
                            Job.company_name == "Acme",
                            Job.title == "Backend Engineer",
                        )
                    )
                    enriched_job = session.scalar(
                        select(Job).where(Job.company_name == "Enrich")
                    )
                    naukri_job = session.scalar(
                        select(Job).where(Job.company_name == "Naukri Co")
                    )
                    sparse_job = session.scalar(
                        select(Job).where(Job.company_name == "Sparse Co")
                    )
                    assert all(
                        job is not None
                        for job in (
                            acme_job,
                            enriched_job,
                            naukri_job,
                            sparse_job,
                        )
                    )
                    assert acme_job is not None
                    assert enriched_job is not None
                    assert naukri_job is not None
                    assert sparse_job is not None
                    assert acme_job.source_type == "greenhouse"
                    assert acme_job.data_completeness == "full"
                    assert {source.portal_name for source in acme_job.portal_sources} == {
                        "linkedin",
                        "indeed",
                    }
                    assert enriched_job.company_id is None
                    assert enriched_job.source_type == "linkedin"
                    assert enriched_job.data_completeness == "partial"
                    assert naukri_job.company_id is None
                    assert naukri_job.source_type == "naukri"
                    assert sparse_job.company_id is None
                    assert sparse_job.data_completeness == "partial"
                    preliminary = session.scalar(
                        select(JobMatch).where(
                            JobMatch.job_id == enriched_job.id,
                            JobMatch.profile_id == profile_id,
                        )
                    )
                    assert preliminary is not None
                    assert preliminary.scoring_version == PARTIAL_SCORING_VERSION
                    assert preliminary.overall_score == 88
                    assert preliminary.recommendation_label == (
                        "Partial / Low Confidence"
                    )
                    assert session.scalar(
                        select(JobMatch).where(JobMatch.job_id == sparse_job.id)
                    ) is None
                    ambiguous_count = session.scalar(
                        select(func.count(Job.id)).where(
                            Job.company_name == "Ambiguous Co",
                            Job.title == "Data Engineer",
                        )
                    )
                    assert ambiguous_count == 3
                    canonical_id = enriched_job.id
                    preliminary_match_id = preliminary.id
                    acme_job_id = acme_job.id
                    naukri_job_id = naukri_job.id
                    sparse_job_id = sparse_job.id

                for source_name in (
                    "greenhouse",
                    "lever",
                    "ashby",
                    "workday",
                    "linkedin",
                    "naukri",
                    "indeed",
                ):
                    response = await client.get(f"/jobs?source={source_name}")
                    assert response.status_code == 200
                    assert "data-job-id=" in response.text
                linkedin_jobs = await client.get("/jobs?source=linkedin")
                indeed_jobs = await client.get("/jobs?source=indeed")
                naukri_jobs = await client.get("/jobs?source=naukri")
                assert linkedin_jobs.text.count(
                    f'data-job-id="{acme_job_id}"'
                ) == 1
                assert indeed_jobs.text.count(f'data-job-id="{acme_job_id}"') == 1
                assert naukri_jobs.text.count(
                    f'data-job-id="{naukri_job_id}"'
                ) == 1
                assert "Not scored" in naukri_jobs.text

                saved = await client.post(
                    f"/jobs/{canonical_id}/state",
                    data={"profile_id": profile_id, "action": "saved"},
                )
                applied = await client.post(
                    f"/jobs/{canonical_id}/state",
                    data={
                        "profile_id": applied_profile_id,
                        "action": "applied",
                        "resume_id": resume_id,
                        "note": "Applied while this was a LinkedIn partial job.",
                    },
                )
                ignored_naukri = await client.post(
                    f"/jobs/{naukri_job_id}/state",
                    data={"profile_id": profile_id, "action": "ignored"},
                )
                saved_naukri = await client.post(
                    f"/jobs/{naukri_job_id}/state",
                    data={"profile_id": profile_id, "action": "saved"},
                )
                applied_naukri = await client.post(
                    f"/jobs/{naukri_job_id}/state",
                    data={"profile_id": profile_id, "action": "applied"},
                )
                assert all(
                    response.status_code == 303
                    for response in (
                        saved,
                        applied,
                        ignored_naukri,
                        saved_naukri,
                        applied_naukri,
                    )
                )

                assert await controller.run_scheduled() is True
                second_scan = controller.snapshot()
                assert second_scan.status == "partial"
                assert second_scan.errors_count == 1
                assert "LinkedIn final-fixture failure" in second_scan.errors[0]

                with application.state.session_factory() as session:
                    enriched = session.get(Job, canonical_id)
                    assert enriched is not None
                    assert enriched.id == canonical_id
                    assert enriched.company_id is not None
                    assert enriched.source_type == "greenhouse"
                    assert enriched.data_completeness == "full"
                    assert "complete job description" in enriched.description
                    assert {source.portal_name for source in enriched.portal_sources} == {
                        "linkedin"
                    }
                    states = tuple(
                        session.scalars(
                            select(JobUserState)
                            .where(JobUserState.job_id == canonical_id)
                            .order_by(JobUserState.profile_id)
                        )
                    )
                    assert [state.state for state in states] == ["saved", "applied"]
                    applied_state = next(
                        state
                        for state in states
                        if state.profile_id == applied_profile_id
                    )
                    assert applied_state.applied_at is not None
                    assert applied_state.resume_id == resume_id
                    assert applied_state.note == (
                        "Applied while this was a LinkedIn partial job."
                    )
                    full_match = session.scalar(
                        select(JobMatch).where(
                            JobMatch.job_id == canonical_id,
                            JobMatch.profile_id == profile_id,
                        )
                    )
                    assert full_match is not None
                    assert full_match.id == preliminary_match_id
                    assert full_match.scoring_version == SCORING_VERSION
                    assert full_match.overall_score == 92
                    assert full_match.recommendation_label == "Excellent"
                    sparse = session.get(Job, sparse_job_id)
                    assert sparse is not None
                    assert sparse.lifecycle_status == "open"
                    assert sparse.consecutive_missing_scans == 0
                    assert session.scalar(
                        select(func.count(NotificationLog.id)).where(
                            NotificationLog.event_key
                            == f"high-match:{canonical_id}:{profile_id}"
                        )
                    ) == 1
                    assert session.scalar(
                        select(func.count(NotificationLog.id)).where(
                            NotificationLog.event_key.like(
                                f"application:{canonical_id}:{applied_profile_id}:%"
                            )
                        )
                    ) == 1
                    latest_linkedin = session.scalar(
                        select(ScanSourceResult)
                        .where(ScanSourceResult.source_type == "linkedin")
                        .order_by(ScanSourceResult.id.desc())
                    )
                    assert latest_linkedin is not None
                    assert latest_linkedin.company_id is None
                    assert latest_linkedin.status == "failed"
                    assert session.scalar(select(func.count(ScanRun.id))) == 2

                detail, dashboard, scans = await asyncio.gather(
                    client.get(f"/jobs/{canonical_id}?profile_id={profile_id}"),
                    client.get("/"),
                    client.get("/scans"),
                )
                assert all(
                    response.status_code == 200
                    for response in (detail, dashboard, scans)
                )
                assert "Job / Enrich / Greenhouse" in detail.text
                assert "Also found on:" in detail.text
                assert "linkedin.com/jobs/view/platform-4100000002" in detail.text
                assert "Authoritative fit using the complete job description" in (
                    detail.text
                )
                assert "LinkedIn" in scans.text
                assert "Naukri" in scans.text
                assert "Indeed" in scans.text
                assert "Non-company source" in scans.text
                assert 'data-source-status="failed"' in scans.text
                assert ai_provider.requests
                assert any(
                    "incomplete search-result metadata" in request.system_prompt
                    for request in ai_provider.requests
                )
                assert any(
                    "Score only facts explicitly present" in request.system_prompt
                    for request in ai_provider.requests
                )
                recommendation_messages = [
                    text for chat_id, text in telegram_sender.messages if chat_id == "-501"
                ]
                assert any(
                    "Preliminary Match — Partial Data / Low Confidence" in message
                    and "Platform Engineer at Enrich" in message
                    for message in recommendation_messages
                )
                assert sum(
                    "Platform Engineer at Enrich" in message
                    for message in recommendation_messages
                ) == 1
                application_messages = [
                    text for chat_id, text in telegram_sender.messages if chat_id == "-502"
                ]
                assert any(
                    "Platform Engineer at Enrich" in message
                    and "Source: LinkedIn" in message
                    for message in application_messages
                )

    asyncio.run(workflow())
