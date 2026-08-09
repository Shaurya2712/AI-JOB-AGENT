import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models.base import utc_now
from app.models.companies import Company
from app.models.jobs import Job
from app.providers.ai.factory import open_ai_provider
from app.providers.jobs.factory import (
    open_ashby_connector,
    open_generic_career_page_connector,
    open_greenhouse_connector,
    open_lever_connector,
    open_workday_connector,
)
from app.providers.search.factory import open_search_provider
from app.repositories.profiles import ProfileRepository
from app.services.ai_matching import AIMatchingService
from app.services.ats_detection import AtsDetectionService
from app.services.job_collection import ConnectorSourceResult, JobCollectionService
from app.services.job_lifecycle import JobLifecycleService
from app.services.job_qualification import qualify_job
from app.services.jobs import JobUpsertService
from app.services.web_discovery import CompanyDiscoveryService


ScanTrigger = Literal["manual", "scheduled"]
ScanStatus = Literal["idle", "running", "success", "partial", "failed"]
SourceStatus = Literal["success", "failed"]
MAX_VISIBLE_SCAN_ERRORS = 20
MATCH_BATCH_SIZE = 100


@dataclass(frozen=True)
class ScanSourceSnapshot:
    company_id: int | None
    source_type: str
    started_at: datetime
    finished_at: datetime
    status: SourceStatus
    jobs_fetched: int = 0
    jobs_new: int = 0
    jobs_updated: int = 0
    error_message: str | None = None
    retry_count: int = 0


@dataclass(frozen=True)
class ScanPipelineResult:
    companies_checked: int
    sources_checked: int
    jobs_fetched: int
    jobs_new: int
    jobs_updated: int
    jobs_scored: int
    strong_matches: int
    errors_count: int
    errors: tuple[str, ...]
    summary: str
    source_results: tuple[ScanSourceSnapshot, ...] = ()


@dataclass(frozen=True)
class ScanRunSnapshot:
    run_id: int | None = None
    status: ScanStatus = "idle"
    trigger_type: ScanTrigger | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    companies_checked: int = 0
    sources_checked: int = 0
    jobs_fetched: int = 0
    jobs_new: int = 0
    jobs_updated: int = 0
    jobs_scored: int = 0
    strong_matches: int = 0
    errors_count: int = 0
    errors: tuple[str, ...] = ()
    summary: str = "No scan has run yet."

    @property
    def is_running(self) -> bool:
        return self.status == "running"


class ScanRunner(Protocol):
    async def run(self, trigger_type: ScanTrigger) -> ScanPipelineResult:
        raise NotImplementedError


class HighMatchNotifier(Protocol):
    async def notify_high_match(self, job_id: int, profile_id: int) -> object:
        raise NotImplementedError


class ScanCompletionNotifier(Protocol):
    async def notify_scan_summary(self, scan: ScanRunSnapshot) -> object:
        raise NotImplementedError


class ScanHistoryWriter(Protocol):
    def start_run(self, trigger_type: ScanTrigger, started_at: datetime) -> int:
        raise NotImplementedError

    def finish_run(
        self,
        snapshot: ScanRunSnapshot,
        source_results: tuple[ScanSourceSnapshot, ...],
    ) -> None:
        raise NotImplementedError


@dataclass
class _RunCounts:
    companies_checked: int = 0
    sources_checked: int = 0
    jobs_fetched: int = 0
    jobs_new: int = 0
    jobs_updated: int = 0
    jobs_scored: int = 0
    strong_matches: int = 0
    errors_count: int = 0
    errors: list[str] = field(default_factory=list)
    new_job_ids: set[int] = field(default_factory=set)
    source_results: list[ScanSourceSnapshot] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors_count += 1
        if len(self.errors) < MAX_VISIBLE_SCAN_ERRORS:
            self.errors.append(message[:500])


class ApplicationScanPipeline:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        recommendation_notifier: HighMatchNotifier | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.recommendation_notifier = recommendation_notifier

    async def run(self, trigger_type: ScanTrigger) -> ScanPipelineResult:
        del trigger_type
        counts = _RunCounts()
        await self._discover_companies(counts)
        self._classify_companies(counts)
        await self._collect_and_persist(counts)
        await self._score_jobs(counts)
        summary = (
            f"Checked {counts.companies_checked} companies and "
            f"{counts.sources_checked} sources; fetched {counts.jobs_fetched} jobs, "
            f"created {counts.jobs_new}, updated {counts.jobs_updated}, "
            f"and scored {counts.jobs_scored}."
        )
        return ScanPipelineResult(
            companies_checked=counts.companies_checked,
            sources_checked=counts.sources_checked,
            jobs_fetched=counts.jobs_fetched,
            jobs_new=counts.jobs_new,
            jobs_updated=counts.jobs_updated,
            jobs_scored=counts.jobs_scored,
            strong_matches=counts.strong_matches,
            errors_count=counts.errors_count,
            errors=tuple(counts.errors),
            summary=summary,
            source_results=tuple(counts.source_results),
        )

    async def _discover_companies(self, counts: _RunCounts) -> None:
        try:
            async with open_search_provider(self.settings) as provider:
                with self.session_factory() as session:
                    result = await CompanyDiscoveryService(
                        session,
                        provider,
                        max_queries=self.settings.search_max_queries_per_run,
                        concurrency=self.settings.search_concurrency,
                    ).discover()
            for error in result.errors:
                counts.add_error(error)
        except Exception:
            counts.add_error("Company discovery failed unexpectedly")

    def _classify_companies(self, counts: _RunCounts) -> None:
        try:
            with self.session_factory() as session:
                result = AtsDetectionService(session).classify_active_companies()
            counts.companies_checked = result.companies_checked
        except Exception:
            counts.add_error("ATS detection failed unexpectedly")

    async def _collect_and_persist(self, counts: _RunCounts) -> None:
        connector_openers = (
            ("greenhouse", open_greenhouse_connector),
            ("lever", open_lever_connector),
            ("ashby", open_ashby_connector),
            ("workday", open_workday_connector),
            ("custom", open_generic_career_page_connector),
        )
        for source_type, opener in connector_openers:
            connector_started_at = utc_now()
            try:
                async with opener(self.settings) as connector:
                    with self.session_factory() as session:
                        result = await JobCollectionService(
                            session,
                            concurrency=self.settings.job_source_concurrency,
                        ).collect(connector)
                counts.sources_checked += result.sources_checked
                counts.jobs_fetched += result.jobs_fetched
                for source_result in result.source_results:
                    self._persist_source(source_result, counts)
            except Exception:
                error_message = f"{source_type}: connector run failed unexpectedly"
                counts.add_error(error_message)
                counts.source_results.append(
                    ScanSourceSnapshot(
                        company_id=None,
                        source_type=source_type,
                        started_at=connector_started_at,
                        finished_at=utc_now(),
                        status="failed",
                        error_message=error_message,
                    )
                )

    def _persist_source(
        self,
        source_result: ConnectorSourceResult,
        counts: _RunCounts,
    ) -> None:
        observed_at = utc_now()
        started_at = source_result.started_at or observed_at
        if source_result.status == "failed":
            error_message = source_result.error_message or (
                f"{source_result.source_type}: source collection failed"
            )
            counts.add_error(error_message)
            metadata_updated = self._update_company_scan(
                source_result.company_id,
                observed_at,
                succeeded=False,
                jobs_seen=0,
            )
            if not metadata_updated:
                counts.add_error("Failed to update company scan metadata")
            counts.source_results.append(
                ScanSourceSnapshot(
                    company_id=source_result.company_id,
                    source_type=source_result.source_type,
                    started_at=started_at,
                    finished_at=source_result.finished_at or utc_now(),
                    status="failed",
                    error_message=error_message,
                    retry_count=source_result.retry_count,
                )
            )
            return

        try:
            with self.session_factory() as session:
                upserts = JobUpsertService(session).upsert_many(
                    source_result.company_id,
                    list(source_result.jobs),
                    seen_at=observed_at,
                )
                seen_job_ids = [result.job.id for result in upserts]
                source_jobs_new = sum(result.created for result in upserts)
                source_jobs_updated = sum(result.updated for result in upserts)
                counts.jobs_new += source_jobs_new
                counts.jobs_updated += source_jobs_updated
                counts.new_job_ids.update(
                    result.job.id for result in upserts if result.created
                )
                JobLifecycleService(
                    session,
                    close_after_missing_scans=(
                        self.settings.job_lifecycle_close_after_missing_scans
                    ),
                ).reconcile_source(
                    source_result.company_id,
                    source_result.source_type,
                    seen_job_ids,
                    scan_succeeded=True,
                    reconciled_at=observed_at,
                )
            metadata_updated = self._update_company_scan(
                source_result.company_id,
                observed_at,
                succeeded=True,
                jobs_seen=len(source_result.jobs),
            )
            if not metadata_updated:
                counts.add_error("Failed to update company scan metadata")
            counts.source_results.append(
                ScanSourceSnapshot(
                    company_id=source_result.company_id,
                    source_type=source_result.source_type,
                    started_at=started_at,
                    finished_at=utc_now(),
                    status="success",
                    jobs_fetched=len(source_result.jobs),
                    jobs_new=source_jobs_new,
                    jobs_updated=source_jobs_updated,
                    retry_count=source_result.retry_count,
                )
            )
        except Exception:
            error_message = (
                f"{source_result.source_type}: failed to persist collected jobs"
            )
            counts.add_error(error_message)
            counts.source_results.append(
                ScanSourceSnapshot(
                    company_id=source_result.company_id,
                    source_type=source_result.source_type,
                    started_at=started_at,
                    finished_at=utc_now(),
                    status="failed",
                    jobs_fetched=len(source_result.jobs),
                    error_message=error_message,
                    retry_count=source_result.retry_count,
                )
            )

    def _update_company_scan(
        self,
        company_id: int,
        observed_at: datetime,
        *,
        succeeded: bool,
        jobs_seen: int,
    ) -> bool:
        try:
            with self.session_factory() as session:
                company = session.get(Company, company_id)
                if company is None:
                    return False
                company.last_scanned_at = observed_at
                if succeeded:
                    company.last_success_at = observed_at
                    company.total_jobs_seen = jobs_seen
                session.commit()
                return True
        except Exception:
            return False

    async def _score_jobs(self, counts: _RunCounts) -> None:
        async with open_ai_provider(self.settings) as provider:
            if not provider.is_configured:
                return
            with self.session_factory() as session:
                profiles = ProfileRepository(session).list_active_profiles()
                last_job_id = 0
                while True:
                    jobs = list(
                        session.scalars(
                            select(Job)
                            .where(
                                Job.lifecycle_status == "open",
                                Job.id > last_job_id,
                            )
                            .order_by(Job.id)
                            .limit(MATCH_BATCH_SIZE)
                        )
                    )
                    if not jobs:
                        break
                    matcher = AIMatchingService(session, provider)
                    for job in jobs:
                        for profile in profiles:
                            if not qualify_job(profile, job).qualified:
                                continue
                            try:
                                result = await matcher.score_job(job.id, profile.id)
                            except Exception:
                                counts.add_error("AI matching failed unexpectedly")
                                continue
                            if result.status == "failed":
                                counts.add_error(result.error or "AI matching failed")
                            elif result.status == "scored":
                                counts.jobs_scored += 1
                                if (
                                    result.match is not None
                                    and result.match.overall_score >= 85
                                ):
                                    counts.strong_matches += 1
                                if (
                                    self.recommendation_notifier is not None
                                    and result.match is not None
                                    and job.id in counts.new_job_ids
                                    and result.match.overall_score
                                    >= self.settings.telegram_match_threshold
                                ):
                                    try:
                                        await self.recommendation_notifier.notify_high_match(
                                            job.id,
                                            profile.id,
                                        )
                                    except Exception:
                                        counts.add_error(
                                            "High-match notification failed unexpectedly"
                                        )
                    last_job_id = jobs[-1].id


class ScanController:
    def __init__(
        self,
        runner: ScanRunner,
        completion_notifier: ScanCompletionNotifier | None = None,
        history_writer: ScanHistoryWriter | None = None,
        initial_snapshot: ScanRunSnapshot | None = None,
    ) -> None:
        self.runner = runner
        self.completion_notifier = completion_notifier
        self.history_writer = history_writer
        self._guard = asyncio.Lock()
        self._suspended = False
        self._task: asyncio.Task[ScanRunSnapshot] | None = None
        self._snapshot = initial_snapshot or ScanRunSnapshot()

    def snapshot(self) -> ScanRunSnapshot:
        return self._snapshot

    async def start_manual(self) -> bool:
        return await self._start("manual")

    async def run_scheduled(self) -> bool:
        started = await self._start("scheduled")
        if not started:
            return False
        task = self._task
        if task is not None:
            await task
        return True

    async def wait_for_idle(self) -> ScanRunSnapshot:
        task = self._task
        if task is not None:
            await task
        return self._snapshot

    async def shutdown(self) -> None:
        task = self._task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def suspend_if_idle(self) -> bool:
        async with self._guard:
            if self._task is not None and not self._task.done():
                return False
            self._suspended = True
            return True

    async def resume(self) -> None:
        async with self._guard:
            self._suspended = False

    async def _start(self, trigger_type: ScanTrigger) -> bool:
        async with self._guard:
            if self._suspended or (
                self._task is not None and not self._task.done()
            ):
                return False
            started_at = utc_now()
            run_id = (
                self.history_writer.start_run(trigger_type, started_at)
                if self.history_writer is not None
                else None
            )
            self._snapshot = ScanRunSnapshot(
                run_id=run_id,
                status="running",
                trigger_type=trigger_type,
                started_at=started_at,
                summary="Scan is running.",
            )
            self._task = asyncio.create_task(
                self._execute(trigger_type, started_at, run_id),
                name=f"job-agent-{trigger_type}-scan",
            )
            return True

    async def _execute(
        self,
        trigger_type: ScanTrigger,
        started_at: datetime,
        run_id: int | None,
    ) -> ScanRunSnapshot:
        source_results: tuple[ScanSourceSnapshot, ...] = ()
        try:
            result = await self.runner.run(trigger_type)
            source_results = result.source_results
            status: ScanStatus = "partial" if result.errors_count else "success"
            snapshot = ScanRunSnapshot(
                run_id=run_id,
                status=status,
                trigger_type=trigger_type,
                started_at=started_at,
                finished_at=utc_now(),
                companies_checked=result.companies_checked,
                sources_checked=result.sources_checked,
                jobs_fetched=result.jobs_fetched,
                jobs_new=result.jobs_new,
                jobs_updated=result.jobs_updated,
                jobs_scored=result.jobs_scored,
                strong_matches=result.strong_matches,
                errors_count=result.errors_count,
                errors=result.errors,
                summary=result.summary,
            )
        except asyncio.CancelledError:
            self._snapshot = ScanRunSnapshot(
                run_id=run_id,
                status="failed",
                trigger_type=trigger_type,
                started_at=started_at,
                finished_at=utc_now(),
                errors_count=1,
                errors=("Scan stopped during application shutdown",),
                summary="Scan stopped during application shutdown.",
            )
            if self.history_writer is not None:
                self.history_writer.finish_run(self._snapshot, source_results)
            raise
        except Exception:
            snapshot = ScanRunSnapshot(
                run_id=run_id,
                status="failed",
                trigger_type=trigger_type,
                started_at=started_at,
                finished_at=utc_now(),
                errors_count=1,
                errors=("Unexpected scan pipeline failure",),
                summary="Scan failed unexpectedly.",
            )
        self._snapshot = snapshot
        if self.history_writer is not None:
            self.history_writer.finish_run(snapshot, source_results)
        if self.completion_notifier is not None:
            try:
                await self.completion_notifier.notify_scan_summary(snapshot)
            except Exception:
                pass
        return snapshot
