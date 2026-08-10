import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.config import Settings
from app.db import create_database_engine, create_session_factory, run_migrations
from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.job_user_state import JobUserState
from app.models.jobs import Job
from app.models.notifications import NotificationLog
from app.models.profiles import CandidateProfile
from app.providers.ai.base import AIProvider, AIProviderError, AIProviderRequest
from app.providers.jobs.base import ConnectorJob
from app.providers.search.base import SearchProviderError, WebSearchResult
from app.schemas.ai import AIMatchOutput
from app.services.ai_matching import (
    AIMatchingService,
    PARTIAL_SCORING_VERSION,
    SCORING_VERSION,
)
from app.services.job_dashboard import JobDashboardService
from app.services.jobs import JobUpsertService
from app.services.notifications import (
    NotificationDestinationService,
    NotificationService,
)
from app.services.portal_discovery import PortalJobCandidate
from app.services.portal_jobs import PortalJobUpsertService
from app.services.scans import (
    ApplicationScanPipeline,
    ScanController,
    ScanSourceSnapshot,
    _RunCounts,
)


OBSERVED_AT = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
USEFUL_SNIPPET = (
    "Join a product engineering team building Python APIs and reliable distributed "
    "services for customers while collaborating with design and operations partners."
)


def _database(tmp_path: Path, name: str):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
        company_seed_path=tmp_path / "unused-seed.json",
        resume_storage_path=tmp_path / "resumes",
        search_provider="disabled",
        ai_provider="disabled",
    )
    run_migrations(settings)
    engine = create_database_engine(settings.database_url)
    return settings, engine, create_session_factory(engine)


def _profile() -> CandidateProfile:
    return CandidateProfile(
        name="Backend Profile",
        is_active=True,
        years_experience=5,
        target_roles_json=["Backend Engineer"],
        role_synonyms_json=["Python Engineer"],
        skills_json=["Python", "PostgreSQL"],
        preferred_locations_json=["Bangalore"],
        work_modes_json=["Remote"],
        excluded_keywords_json=[],
        notes="",
    )


def _company(name: str = "Acme") -> Company:
    return Company(
        name=name,
        website_url=f"https://{name.casefold()}.example",
        careers_url=f"https://jobs.{name.casefold()}.example",
        provider_type="greenhouse",
        provider_identifier=name.casefold(),
        discovery_source="seed",
        is_active=True,
        provider_supported=True,
        total_jobs_seen=0,
    )


def _partial_candidate(
    portal: str,
    source_id: str,
    *,
    company: str = "Acme",
    snippet: str = USEFUL_SNIPPET,
) -> PortalJobCandidate:
    urls = {
        "linkedin": f"https://www.linkedin.com/jobs/view/backend-{source_id}",
        "naukri": f"https://www.naukri.com/job-listings-backend-{source_id}",
        "indeed": f"https://www.indeed.com/viewjob?jk={source_id}",
    }
    return PortalJobCandidate(
        portal=portal,  # type: ignore[arg-type]
        source_job_id=source_id,
        original_url=urls[portal],
        title="Backend Engineer",
        company_name=company,
        location_text="Bangalore",
        snippet=snippet,
    )


def _output(*, overall: int, partial: bool) -> AIMatchOutput:
    return AIMatchOutput(
        overall_score=overall,
        role_score=96,
        skills_score=92,
        experience_score=None if partial else 90,
        location_score=94,
        freshness_score=None if partial else 88,
        seniority_score=86,
        salary_score=None,
        matching_skills=["Python"],
        missing_skills=["Kubernetes"],
        concerns=["The available job evidence is incomplete"] if partial else [],
        explanation=(
            "Preliminary role and explicit Python evidence align."
            if partial
            else "The full job description strongly aligns."
        ),
        suggested_resume_id=None,
        profile_suggestions=[],
    )


class SequenceAIProvider(AIProvider):
    name = "fake"
    model = "fixture"

    def __init__(self, outputs: list[AIMatchOutput | Exception]) -> None:
        self.outputs = outputs
        self.requests: list[AIProviderRequest] = []

    @property
    def is_configured(self) -> bool:
        return True

    async def score_match(self, request: AIProviderRequest) -> AIMatchOutput:
        self.requests.append(request)
        output = self.outputs[len(self.requests) - 1]
        if isinstance(output, Exception):
            raise output
        return output


def test_shared_pipeline_order_manual_scheduled_and_overlap_guard(
    tmp_path: Path,
) -> None:
    settings, engine, session_factory = _database(tmp_path, "shared-pipeline.db")
    calls: list[str] = []

    class RecordingPipeline(ApplicationScanPipeline):
        async def _discover_companies(self, _counts: _RunCounts) -> None:
            calls.append("company-discovery")
            await asyncio.sleep(0.01)

        def _classify_companies(self, _counts: _RunCounts) -> None:
            calls.append("ats-detection")

        async def _collect_and_persist(self, _counts: _RunCounts) -> None:
            calls.append("ats-collection")

        async def _discover_and_persist_portal_jobs(
            self,
            counts: _RunCounts,
        ) -> None:
            calls.append("portal-discovery")
            counts.sources_checked += 1
            counts.add_error("linkedin: fixture discovery failure")
            counts.source_results.append(
                ScanSourceSnapshot(
                    company_id=None,
                    source_type="linkedin",
                    started_at=OBSERVED_AT,
                    finished_at=OBSERVED_AT,
                    status="failed",
                    error_message="linkedin: fixture discovery failure",
                )
            )

        async def _score_jobs(self, _counts: _RunCounts) -> None:
            calls.append("matching")

    async def scenario() -> None:
        controller = ScanController(RecordingPipeline(session_factory, settings))
        assert await controller.start_manual() is True
        assert await controller.start_manual() is False
        manual = await controller.wait_for_idle()
        assert manual.status == "partial"
        assert manual.sources_checked == 1
        assert manual.errors == ("linkedin: fixture discovery failure",)
        assert await controller.run_scheduled() is True
        assert controller.snapshot().status == "partial"

    try:
        asyncio.run(scenario())
        expected = [
            "company-discovery",
            "ats-detection",
            "ats-collection",
            "portal-discovery",
            "matching",
        ]
        assert calls == expected * 2
    finally:
        engine.dispose()


def test_portal_sources_are_isolated_persisted_logged_and_never_closed_by_absence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, engine, session_factory = _database(tmp_path, "portal-sources.db")
    with session_factory() as session:
        session.add(_profile())
        session.commit()

    class PortalSearchProvider:
        name = "fixture-search"
        is_configured = True

        async def search(self, query: str) -> list[WebSearchResult]:
            if "linkedin.com" in query:
                raise SearchProviderError("LinkedIn fixture unavailable")
            if "naukri.com" in query:
                return [
                    WebSearchResult(
                        title="Backend Engineer job at Naukri Co in Bangalore",
                        url="https://www.naukri.com/job-listings-backend-1234567890",
                        description=USEFUL_SNIPPET,
                    )
                ]
            return [
                WebSearchResult(
                    title="Backend Engineer at Indeed Co in Bangalore",
                    url="https://www.indeed.com/viewjob?jk=indeed123",
                    description=USEFUL_SNIPPET,
                )
            ]

    @asynccontextmanager
    async def provider_context(_settings):
        yield PortalSearchProvider()

    monkeypatch.setattr("app.services.scans.open_search_provider", provider_context)
    pipeline = ApplicationScanPipeline(session_factory, settings)

    async def scenario() -> _RunCounts:
        counts = _RunCounts()
        await pipeline._discover_and_persist_portal_jobs(counts)
        with session_factory() as session:
            jobs = tuple(session.scalars(select(Job).order_by(Job.id)))
            assert len(jobs) == 2
            jobs[0].consecutive_missing_scans = 2
            jobs[0].lifecycle_status = "possibly_closed"
            tracked_id = jobs[0].id
            session.commit()

        class EmptyProvider(PortalSearchProvider):
            async def search(self, _query: str) -> list[WebSearchResult]:
                return []

        @asynccontextmanager
        async def empty_context(_settings):
            yield EmptyProvider()

        monkeypatch.setattr("app.services.scans.open_search_provider", empty_context)
        await pipeline._discover_and_persist_portal_jobs(_RunCounts())
        with session_factory() as session:
            tracked = session.get(Job, tracked_id)
            assert tracked is not None
            assert tracked.consecutive_missing_scans == 2
            assert tracked.lifecycle_status == "possibly_closed"
        return counts

    try:
        counts = asyncio.run(scenario())
        assert counts.sources_checked == 3
        assert counts.jobs_fetched == 2
        assert counts.jobs_new == 2
        assert counts.errors_count == 1
        assert [source.source_type for source in counts.source_results] == [
            "linkedin",
            "naukri",
            "indeed",
        ]
        assert [source.status for source in counts.source_results] == [
            "failed",
            "success",
            "success",
        ]
        assert counts.source_results[0].company_id is None
        assert "LinkedIn fixture unavailable" in (
            counts.source_results[0].error_message or ""
        )
    finally:
        engine.dispose()


def test_partial_scoring_gate_low_confidence_and_authoritative_full_rescore(
    tmp_path: Path,
) -> None:
    _, engine, session_factory = _database(tmp_path, "partial-rescore.db")
    provider = SequenceAIProvider(
        [_output(overall=96, partial=True), _output(overall=93, partial=False)]
    )
    try:
        with session_factory() as session:
            profile = _profile()
            session.add(profile)
            session.commit()
            partial = PortalJobUpsertService(session).upsert(
                _partial_candidate("linkedin", "1234567890"),
                seen_at=OBSERVED_AT,
            ).job
            state = JobUserState(
                job_id=partial.id,
                profile_id=profile.id,
                state="saved",
                note="Keep this canonical opportunity",
            )
            session.add(state)
            session.commit()

            matcher = AIMatchingService(session, provider)
            preliminary = asyncio.run(matcher.score_job(partial.id, profile.id))
            unchanged = asyncio.run(matcher.score_job(partial.id, profile.id))

            assert preliminary.status == "scored"
            assert preliminary.match is not None
            preliminary_match_id = preliminary.match.id
            assert preliminary.match.overall_score == 89
            assert preliminary.match.scoring_version == PARTIAL_SCORING_VERSION
            assert preliminary.match.recommendation_label == (
                "Partial / Low Confidence"
            )
            assert preliminary.match.experience_score is None
            assert preliminary.match.freshness_score is None
            assert preliminary.match.seniority_score is None
            assert preliminary.match.salary_score is None
            assert preliminary.match.missing_skills_json == []
            assert unchanged.status == "skipped"
            assert len(provider.requests) == 1
            assert "incomplete search-result metadata" in (
                provider.requests[0].system_prompt
            )
            assert "Never invent salary" in provider.requests[0].system_prompt

            company = _company()
            session.add(company)
            session.commit()
            enrichment = JobUpsertService(session).upsert(
                company.id,
                ConnectorJob(
                    source_type="greenhouse",
                    source_job_id="ats-123",
                    title="Backend Engineer",
                    location_text="Bangalore",
                    description=(
                        "Build Python APIs and distributed services. Requires five "
                        "years of experience working with PostgreSQL."
                    ),
                    job_url="https://jobs.acme.example/ats-123",
                ),
                seen_at=OBSERVED_AT,
            )
            assert enrichment.job.id == partial.id
            assert enrichment.upgraded_to_full is True

            authoritative = asyncio.run(
                matcher.score_job(enrichment.job.id, profile.id)
            )
            assert authoritative.status == "scored"
            assert authoritative.match is not None
            assert authoritative.match.id == preliminary_match_id
            assert authoritative.match.scoring_version == SCORING_VERSION
            assert authoritative.match.overall_score == 93
            assert authoritative.match.recommendation_label == "Excellent"
            assert len(provider.requests) == 2
            assert "incomplete portal search metadata" not in (
                provider.requests[1].user_prompt
            )
            retained_state = session.scalar(select(JobUserState))
            assert retained_state is not None
            assert retained_state.state == "saved"
            assert retained_state.note == "Keep this canonical opportunity"
            assert session.scalar(select(func.count(JobMatch.id))) == 1
    finally:
        engine.dispose()


def test_insufficient_partial_metadata_is_not_scored_and_makes_no_ai_call(
    tmp_path: Path,
) -> None:
    _, engine, session_factory = _database(tmp_path, "partial-gate.db")
    provider = SequenceAIProvider([])
    try:
        with session_factory() as session:
            profile = _profile()
            session.add(profile)
            session.commit()
            job = PortalJobUpsertService(session).upsert(
                _partial_candidate(
                    "linkedin",
                    "1234567891",
                    snippet="Apply now. Click here to apply. View this job.",
                )
            ).job
            result = asyncio.run(
                AIMatchingService(session, provider).score_job(job.id, profile.id)
            )
            assert result.status == "skipped"
            assert result.match is None
            assert provider.requests == []
            assert session.scalar(select(func.count(JobMatch.id))) == 0
    finally:
        engine.dispose()


def test_full_jobs_still_require_all_v1_non_salary_components(
    tmp_path: Path,
) -> None:
    _, engine, session_factory = _database(tmp_path, "full-validation.db")
    provider = SequenceAIProvider([_output(overall=90, partial=True)])
    try:
        with session_factory() as session:
            profile = _profile()
            company = _company()
            session.add_all([profile, company])
            session.commit()
            job = JobUpsertService(session).upsert(
                company.id,
                ConnectorJob(
                    source_type="greenhouse",
                    source_job_id="strict-full",
                    title="Backend Engineer",
                    location_text="Bangalore",
                    description="A complete fixture job description.",
                    job_url="https://jobs.acme.example/strict-full",
                ),
            ).job
            result = asyncio.run(
                AIMatchingService(session, provider).score_job(job.id, profile.id)
            )
            assert result.status == "failed"
            assert result.error == "AI provider returned an invalid structured match"
            assert session.scalar(select(func.count(JobMatch.id))) == 0
    finally:
        engine.dispose()


def test_partial_queue_uses_existing_queue_and_full_wins_equal_score(
    tmp_path: Path,
) -> None:
    _, engine, session_factory = _database(tmp_path, "partial-queue.db")
    try:
        with session_factory() as session:
            profile = _profile()
            company = _company("Queue")
            session.add_all([profile, company])
            session.commit()
            partial = PortalJobUpsertService(session).upsert(
                _partial_candidate("indeed", "queue123", company="Portal Queue")
            ).job
            ignored = PortalJobUpsertService(session).upsert(
                _partial_candidate("naukri", "1234567892", company="Ignored Queue")
            ).job
            full = Job(
                company_id=company.id,
                company_name=company.name,
                source_type="greenhouse",
                source_job_id="queue-full",
                canonical_url="https://jobs.queue.example/queue-full",
                title="Backend Engineer",
                normalized_title="backend engineer",
                location_text="Bangalore",
                description="Full description",
                description_hash="a" * 64,
                dedupe_signature="b" * 64,
                data_completeness="full",
                discovered_at=OBSERVED_AT,
                last_seen_at=OBSERVED_AT,
                lifecycle_status="open",
            )
            session.add(full)
            session.flush()
            for job, version, label in (
                (partial, PARTIAL_SCORING_VERSION, "Partial / Low Confidence"),
                (ignored, PARTIAL_SCORING_VERSION, "Partial / Low Confidence"),
                (full, SCORING_VERSION, "Strong"),
            ):
                session.add(
                    JobMatch(
                        job_id=job.id,
                        profile_id=profile.id,
                        ai_provider="fake",
                        ai_model="fixture",
                        scoring_version=version,
                        overall_score=88,
                        role_score=90,
                        skills_score=None if job.data_completeness == "partial" else 88,
                        experience_score=None,
                        location_score=90,
                        freshness_score=None,
                        seniority_score=85,
                        salary_score=None,
                        recommendation_label=label,
                        matching_skills_json=[],
                        missing_skills_json=[],
                        concerns_json=[],
                        explanation="Fixture",
                        source_job_hash=f"{job.id:064d}",
                        scored_at=OBSERVED_AT,
                    )
                )
            session.add(
                JobUserState(job_id=ignored.id, profile_id=profile.id, state="ignored")
            )
            session.commit()

            queue = JobDashboardService(session).daily_action_queue(target=10)
            assert [item.id for item in queue.items] == [full.id, partial.id]
            assert queue.items[1].company_name == "Portal Queue"
            assert queue.items[1].recommendation_label == "Partial / Low Confidence"
    finally:
        engine.dispose()


class RecordingTelegramSender:
    is_configured = True

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_message(self, _chat_id: str, text: str) -> None:
        self.messages.append(text)


def test_partial_telegram_label_and_enrichment_idempotency(
    tmp_path: Path,
) -> None:
    _, engine, session_factory = _database(tmp_path, "partial-telegram.db")
    sender = RecordingTelegramSender()
    try:
        with session_factory() as session:
            profile = _profile()
            session.add(profile)
            session.commit()
            first_job = PortalJobUpsertService(session).upsert(
                _partial_candidate("linkedin", "1234567893")
            ).job
            second_job = PortalJobUpsertService(session).upsert(
                _partial_candidate(
                    "indeed",
                    "telegram123",
                    company="Second Acme",
                )
            ).job
            session.add_all(
                [
                    JobMatch(
                        job_id=first_job.id,
                        profile_id=profile.id,
                        ai_provider="fake",
                        ai_model="fixture",
                        scoring_version=PARTIAL_SCORING_VERSION,
                        overall_score=87,
                        role_score=92,
                        skills_score=85,
                        experience_score=None,
                        location_score=90,
                        freshness_score=None,
                        seniority_score=80,
                        salary_score=None,
                        recommendation_label="Partial / Low Confidence",
                        matching_skills_json=["Python"],
                        missing_skills_json=[],
                        concerns_json=["Partial data"],
                        explanation="Preliminary fixture",
                        source_job_hash="c" * 64,
                        scored_at=OBSERVED_AT,
                    ),
                    JobMatch(
                        job_id=second_job.id,
                        profile_id=profile.id,
                        ai_provider="fake",
                        ai_model="fixture",
                        scoring_version=PARTIAL_SCORING_VERSION,
                        overall_score=80,
                        role_score=85,
                        skills_score=None,
                        experience_score=None,
                        location_score=85,
                        freshness_score=None,
                        seniority_score=75,
                        salary_score=None,
                        recommendation_label="Partial / Low Confidence",
                        matching_skills_json=[],
                        missing_skills_json=[],
                        concerns_json=["Partial data"],
                        explanation="Below threshold fixture",
                        source_job_hash="d" * 64,
                        scored_at=OBSERVED_AT,
                    ),
                ]
            )
            NotificationDestinationService(session).configure(
                "recommendation",
                name="High matches",
                telegram_chat_id="-3001",
                is_enabled=True,
            )

        notifications = NotificationService(
            session_factory,
            sender,
            match_threshold=85,
        )

        async def scenario() -> None:
            first = await notifications.notify_high_match(first_job.id, profile.id)
            assert first.sent == 1
            with session_factory() as session:
                stored_job = session.get(Job, first_job.id)
                stored_match = session.scalar(
                    select(JobMatch).where(JobMatch.job_id == first_job.id)
                )
                assert stored_job is not None and stored_match is not None
                stored_job.data_completeness = "full"
                stored_match.scoring_version = SCORING_VERSION
                stored_match.overall_score = 92
                stored_match.recommendation_label = "Excellent"
                session.commit()
            duplicate = await notifications.notify_high_match(
                first_job.id,
                profile.id,
            )
            assert duplicate.skipped == 1

            below = await notifications.notify_high_match(second_job.id, profile.id)
            assert below.skipped == 1
            with session_factory() as session:
                stored_job = session.get(Job, second_job.id)
                stored_match = session.scalar(
                    select(JobMatch).where(JobMatch.job_id == second_job.id)
                )
                assert stored_job is not None and stored_match is not None
                stored_job.data_completeness = "full"
                stored_match.scoring_version = SCORING_VERSION
                stored_match.overall_score = 91
                stored_match.recommendation_label = "Excellent"
                session.commit()
            first_full = await notifications.notify_high_match(
                second_job.id,
                profile.id,
            )
            assert first_full.sent == 1

        asyncio.run(scenario())

        assert len(sender.messages) == 2
        assert "Preliminary Match — Partial Data / Low Confidence" in sender.messages[0]
        assert "Only search-result metadata was analyzed" in sender.messages[0]
        assert first_job.canonical_url in sender.messages[0]
        assert "New high match: 91% Excellent" in sender.messages[1]
        with session_factory() as session:
            logs = tuple(
                session.scalars(select(NotificationLog).order_by(NotificationLog.id))
            )
            assert [log.event_key for log in logs] == [
                f"high-match:{first_job.id}:{profile.id}",
                f"high-match:{second_job.id}:{profile.id}",
            ]
    finally:
        engine.dispose()


def test_ai_failure_isolated_while_later_partial_job_scores(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, engine, session_factory = _database(tmp_path, "partial-ai-failure.db")
    provider = SequenceAIProvider(
        [AIProviderError("fixture AI unavailable"), _output(overall=90, partial=True)]
    )
    try:
        with session_factory() as session:
            profile = _profile()
            session.add(profile)
            session.commit()
            first = PortalJobUpsertService(session).upsert(
                _partial_candidate("linkedin", "1234567894", company="First AI")
            ).job
            second = PortalJobUpsertService(session).upsert(
                _partial_candidate("indeed", "failure123", company="Second AI")
            ).job
            ids = {first.id, second.id}

        @asynccontextmanager
        async def ai_context(_settings):
            yield provider

        monkeypatch.setattr("app.services.scans.open_ai_provider", ai_context)
        counts = _RunCounts(notification_job_ids=ids)
        asyncio.run(ApplicationScanPipeline(session_factory, settings)._score_jobs(counts))

        assert counts.errors_count == 1
        assert counts.jobs_scored == 1
        assert counts.strong_matches == 1
        with session_factory() as session:
            assert session.scalar(select(func.count(Job.id))) == 2
            assert session.scalar(select(func.count(JobMatch.id))) == 1
    finally:
        engine.dispose()
