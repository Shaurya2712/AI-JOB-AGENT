from dataclasses import dataclass
from datetime import datetime
import re
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import utc_now
from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.job_user_state import JobUserState
from app.models.jobs import Job
from app.models.notifications import (
    NotificationDestination,
    NotificationDestinationType,
    NotificationLog,
)
from app.models.profiles import CandidateProfile
from app.providers.telegram import TelegramDeliveryError


DESTINATION_LABELS: dict[NotificationDestinationType, str] = {
    "recommendation": "High-match recommendations",
    "application_activity": "Application activity",
    "scan_summary": "Search/run summaries",
}
DESTINATION_TYPES = tuple(DESTINATION_LABELS)
CHAT_ID_PATTERN = re.compile(r"^-?\d{1,20}$")
MAX_NOTIFICATION_ERROR_CHARS = 500


class TelegramSender(Protocol):
    @property
    def is_configured(self) -> bool:
        raise NotImplementedError

    async def send_message(self, chat_id: str, text: str) -> None:
        raise NotImplementedError


class CompletedScan(Protocol):
    run_id: int | None
    status: str
    trigger_type: str | None
    started_at: datetime | None
    companies_checked: int
    sources_checked: int
    jobs_fetched: int
    jobs_new: int
    jobs_updated: int
    jobs_scored: int
    strong_matches: int
    errors_count: int


class DestinationInputError(ValueError):
    pass


@dataclass(frozen=True)
class DestinationView:
    type: NotificationDestinationType
    label: str
    name: str
    telegram_chat_id: str
    is_enabled: bool


@dataclass(frozen=True)
class NotificationResult:
    sent: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(frozen=True)
class _Delivery:
    destination_id: int
    chat_id: str


class NotificationDestinationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_destinations(self) -> tuple[DestinationView, ...]:
        stored = {
            row.type: row
            for row in self.session.scalars(
                select(NotificationDestination).order_by(NotificationDestination.id)
            )
        }
        return tuple(
            DestinationView(
                type=destination_type,
                label=label,
                name=(
                    stored[destination_type].name
                    if destination_type in stored
                    else label
                ),
                telegram_chat_id=(
                    stored[destination_type].telegram_chat_id
                    if destination_type in stored
                    else ""
                ),
                is_enabled=(
                    stored[destination_type].is_enabled
                    if destination_type in stored
                    else False
                ),
            )
            for destination_type, label in DESTINATION_LABELS.items()
        )

    def configure(
        self,
        destination_type: str,
        *,
        name: str,
        telegram_chat_id: str,
        is_enabled: bool,
    ) -> NotificationDestination:
        if destination_type not in DESTINATION_TYPES:
            raise DestinationInputError("Unknown notification destination")
        normalized_name = " ".join(name.split())
        normalized_chat_id = telegram_chat_id.strip()
        if not normalized_name or len(normalized_name) > 120:
            raise DestinationInputError(
                "Destination name is required and must be 120 characters or fewer"
            )
        if normalized_chat_id and CHAT_ID_PATTERN.fullmatch(normalized_chat_id) is None:
            raise DestinationInputError(
                "Telegram chat ID must contain only an optional minus sign and digits"
            )
        if is_enabled and not normalized_chat_id:
            raise DestinationInputError(
                "A Telegram chat ID is required before enabling a destination"
            )

        destination = self.session.scalar(
            select(NotificationDestination).where(
                NotificationDestination.type == destination_type
            )
        )
        if destination is None:
            destination = NotificationDestination(type=destination_type)
            self.session.add(destination)
        destination.name = normalized_name
        destination.telegram_chat_id = normalized_chat_id
        destination.is_enabled = is_enabled
        try:
            self.session.commit()
            self.session.refresh(destination)
        except Exception:
            self.session.rollback()
            raise
        return destination


class NotificationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        sender: TelegramSender,
        *,
        match_threshold: int = 85,
    ) -> None:
        self.session_factory = session_factory
        self.sender = sender
        self.match_threshold = match_threshold

    async def notify_high_match(
        self,
        job_id: int,
        profile_id: int,
    ) -> NotificationResult:
        with self.session_factory() as session:
            row = session.execute(
                select(Job, Company, CandidateProfile, JobMatch)
                .join(Company, Company.id == Job.company_id)
                .join(JobMatch, JobMatch.job_id == Job.id)
                .join(CandidateProfile, CandidateProfile.id == JobMatch.profile_id)
                .where(
                    Job.id == job_id,
                    JobMatch.profile_id == profile_id,
                    JobMatch.overall_score >= self.match_threshold,
                )
            ).one_or_none()
            if row is None:
                return NotificationResult(skipped=1)
            job, company, profile, match = row
            message = (
                f"New high match: {match.overall_score}% {match.recommendation_label}\n"
                f"{job.title} at {company.name}\n"
                f"Profile: {profile.name}\n"
                f"Location: {job.location_text or 'Not listed'}\n"
                f"{job.canonical_url}"
            )
        return await self._deliver(
            "recommendation",
            event_key=f"high-match:{job_id}:{profile_id}",
            message=message,
            job_id=job_id,
        )

    async def notify_application(
        self,
        job_id: int,
        profile_id: int,
    ) -> NotificationResult:
        with self.session_factory() as session:
            row = session.execute(
                select(Job, Company, CandidateProfile, JobUserState)
                .join(Company, Company.id == Job.company_id)
                .join(JobUserState, JobUserState.job_id == Job.id)
                .join(CandidateProfile, CandidateProfile.id == JobUserState.profile_id)
                .where(
                    Job.id == job_id,
                    JobUserState.profile_id == profile_id,
                    JobUserState.state == "applied",
                    JobUserState.applied_at.is_not(None),
                )
            ).one_or_none()
            if row is None:
                return NotificationResult(skipped=1)
            job, company, profile, state = row
            applied_at = state.applied_at
            assert applied_at is not None
            message = (
                f"Application recorded\n"
                f"{job.title} at {company.name}\n"
                f"Profile: {profile.name}\n"
                f"Applied: {applied_at.isoformat()}\n"
                f"{job.canonical_url}"
            )
        return await self._deliver(
            "application_activity",
            event_key=f"application:{job_id}:{profile_id}:{applied_at.isoformat()}",
            message=message,
            job_id=job_id,
        )

    async def notify_scan_summary(self, scan: CompletedScan) -> NotificationResult:
        if scan.started_at is None or scan.trigger_type is None:
            return NotificationResult(skipped=1)
        message = (
            f"Scan {scan.status}: {scan.trigger_type}\n"
            f"Companies: {scan.companies_checked} · Sources: {scan.sources_checked}\n"
            f"Jobs: {scan.jobs_fetched} fetched, {scan.jobs_new} new, "
            f"{scan.jobs_updated} updated\n"
            f"Scored: {scan.jobs_scored} · Strong matches: {scan.strong_matches}\n"
            f"Errors: {scan.errors_count}"
        )
        return await self._deliver(
            "scan_summary",
            event_key=(
                f"scan-summary:{scan.trigger_type}:{scan.started_at.isoformat()}"
            ),
            message=message,
            scan_run_id=scan.run_id,
        )

    async def _deliver(
        self,
        destination_type: NotificationDestinationType,
        *,
        event_key: str,
        message: str,
        job_id: int | None = None,
        scan_run_id: int | None = None,
    ) -> NotificationResult:
        normalized_event_key = event_key[:255]
        deliveries = self._reserve_deliveries(
            destination_type,
            event_key=normalized_event_key,
            job_id=job_id,
            scan_run_id=scan_run_id,
        )
        if not deliveries:
            return NotificationResult(skipped=1)

        sent = 0
        failed = 0
        for delivery in deliveries:
            try:
                await self.sender.send_message(delivery.chat_id, message)
            except TelegramDeliveryError as error:
                self._finish_delivery(
                    delivery.destination_id,
                    normalized_event_key,
                    status="failed",
                    error_message=str(error),
                )
                failed += 1
            except Exception:
                self._finish_delivery(
                    delivery.destination_id,
                    normalized_event_key,
                    status="failed",
                    error_message="Telegram delivery failed unexpectedly",
                )
                failed += 1
            else:
                self._finish_delivery(
                    delivery.destination_id,
                    normalized_event_key,
                    status="sent",
                )
                sent += 1
        return NotificationResult(sent=sent, failed=failed)

    def _reserve_deliveries(
        self,
        destination_type: NotificationDestinationType,
        *,
        event_key: str,
        job_id: int | None,
        scan_run_id: int | None,
    ) -> tuple[_Delivery, ...]:
        with self.session_factory() as session:
            destinations = tuple(
                session.scalars(
                    select(NotificationDestination).where(
                        NotificationDestination.type == destination_type,
                        NotificationDestination.is_enabled.is_(True),
                        NotificationDestination.telegram_chat_id != "",
                    )
                )
            )

        deliveries: list[_Delivery] = []
        for destination in destinations:
            with self.session_factory() as session:
                existing = session.scalar(
                    select(NotificationLog).where(
                        NotificationLog.destination_id == destination.id,
                        NotificationLog.event_key == event_key,
                    )
                )
                if existing is None:
                    existing = NotificationLog(
                        destination_id=destination.id,
                        job_id=job_id,
                        scan_run_id=scan_run_id,
                        event_key=event_key,
                        status="pending",
                    )
                    session.add(existing)
                else:
                    if existing.status in {"pending", "sent"}:
                        continue
                    claimed = session.execute(
                        update(NotificationLog)
                        .where(
                            NotificationLog.id == existing.id,
                            NotificationLog.status == "failed",
                        )
                        .values(status="pending", error_message=None)
                    )
                    if claimed.rowcount != 1:
                        session.rollback()
                        continue
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    continue
            deliveries.append(
                _Delivery(
                    destination_id=destination.id,
                    chat_id=destination.telegram_chat_id,
                )
            )
        return tuple(deliveries)

    def _finish_delivery(
        self,
        destination_id: int,
        event_key: str,
        *,
        status: str,
        error_message: str | None = None,
    ) -> None:
        with self.session_factory() as session:
            log = session.scalar(
                select(NotificationLog).where(
                    NotificationLog.destination_id == destination_id,
                    NotificationLog.event_key == event_key,
                )
            )
            if log is None:
                return
            log.status = status
            log.sent_at = utc_now() if status == "sent" else None
            log.error_message = (
                error_message[:MAX_NOTIFICATION_ERROR_CHARS]
                if error_message
                else None
            )
            session.commit()
