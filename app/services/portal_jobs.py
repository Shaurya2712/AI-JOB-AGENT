from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import unicodedata

from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.jobs import Job
from app.models.portal_sources import PortalJobSource
from app.repositories.jobs import JobRepository
from app.services.job_normalization import (
    cross_source_signature,
    normalize_display_text,
    normalize_identity_text,
    normalize_job_url,
)
from app.services.portal_discovery import PortalJobCandidate
from app.services.search_queries import PORTAL_NAMES


MAX_PORTAL_SNIPPET_CHARS = 10_000


class PortalJobPersistenceError(ValueError):
    pass


class PortalJobIdentityConflictError(PortalJobPersistenceError):
    pass


@dataclass(frozen=True)
class PortalJobUpsertResult:
    job: Job
    source: PortalJobSource
    job_created: bool
    source_created: bool
    materially_changed: bool


class PortalJobUpsertService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = JobRepository(session)

    def upsert(
        self,
        candidate: PortalJobCandidate,
        *,
        seen_at: datetime | None = None,
    ) -> PortalJobUpsertResult:
        return self.upsert_many([candidate], seen_at=seen_at)[0]

    def upsert_many(
        self,
        candidates: list[PortalJobCandidate],
        *,
        seen_at: datetime | None = None,
    ) -> tuple[PortalJobUpsertResult, ...]:
        observed_at = self._observed_at(seen_at)
        normalized_candidates = tuple(self._normalize(candidate) for candidate in candidates)
        try:
            results = tuple(
                self._upsert_normalized(candidate, observed_at)
                for candidate in normalized_candidates
            )
            self.session.commit()
            for result in results:
                self.session.refresh(result.job)
                self.session.refresh(result.source)
            return results
        except Exception:
            self.session.rollback()
            raise

    def _upsert_normalized(
        self,
        candidate: PortalJobCandidate,
        observed_at: datetime,
    ) -> PortalJobUpsertResult:
        identity_match, url_match = self.repository.find_portal_sources(
            candidate.portal,
            source_job_id=candidate.source_job_id,
            original_url=candidate.original_url,
        )
        if (
            identity_match is not None
            and url_match is not None
            and identity_match.id != url_match.id
        ):
            raise PortalJobIdentityConflictError(
                "Portal identity and URL belong to different observations"
            )

        existing_source = identity_match or url_match
        if existing_source is not None:
            return self._refresh_existing(existing_source, candidate, observed_at)

        signature = cross_source_signature(
            candidate.company_name,
            candidate.title,
            candidate.location_text,
        )
        matches = (
            self.repository.find_cross_source_candidates(signature)
            if signature is not None
            else []
        )
        job = matches[0] if len(matches) == 1 else None
        job_created = job is None
        if job is None:
            description_hash = _hash_text(
                " ".join(candidate.snippet.casefold().split())
            )
            dedupe_signature = _portal_dedupe_signature(
                candidate,
                description_hash,
            )
            job = Job(
                company_id=None,
                company_name=candidate.company_name,
                source_type=candidate.portal,
                source_job_id=candidate.source_job_id,
                canonical_url=candidate.original_url,
                title=candidate.title,
                normalized_title=normalize_identity_text(candidate.title),
                location_text=candidate.location_text,
                description=candidate.snippet,
                description_hash=description_hash,
                dedupe_signature=dedupe_signature,
                cross_source_signature=signature,
                data_completeness="partial",
                discovered_at=observed_at,
                last_seen_at=observed_at,
                consecutive_missing_scans=0,
                lifecycle_status="open",
                created_at=observed_at,
                updated_at=observed_at,
            )
            self.repository.add(job)
            self.session.flush()
        else:
            job.last_seen_at = self._latest(job.last_seen_at, observed_at)

        source = PortalJobSource(
            job_id=job.id,
            portal_name=candidate.portal,
            source_job_id=candidate.source_job_id,
            original_url=candidate.original_url,
            title=candidate.title,
            company_name=candidate.company_name,
            location_text=candidate.location_text,
            snippet=candidate.snippet,
            data_completeness="partial",
            first_seen_at=observed_at,
            last_seen_at=observed_at,
        )
        self.repository.add_portal_source(source)
        return PortalJobUpsertResult(
            job=job,
            source=source,
            job_created=job_created,
            source_created=True,
            materially_changed=job_created,
        )

    def _refresh_existing(
        self,
        source: PortalJobSource,
        candidate: PortalJobCandidate,
        observed_at: datetime,
    ) -> PortalJobUpsertResult:
        job = source.job
        source_changed = (
            source.source_job_id != candidate.source_job_id
            or source.original_url != candidate.original_url
            or source.title != candidate.title
            or source.company_name != candidate.company_name
            or source.location_text != candidate.location_text
            or source.snippet != candidate.snippet
        )
        source.source_job_id = candidate.source_job_id
        source.original_url = candidate.original_url
        source.title = candidate.title
        source.company_name = candidate.company_name
        source.location_text = candidate.location_text
        source.snippet = candidate.snippet
        source.data_completeness = "partial"
        source.last_seen_at = self._latest(source.last_seen_at, observed_at)

        material_changed = False
        if job.data_completeness == "partial":
            description_hash = _hash_text(
                " ".join(candidate.snippet.casefold().split())
            )
            signature = cross_source_signature(
                candidate.company_name,
                candidate.title,
                candidate.location_text,
            )
            material_changed = (
                job.source_type != candidate.portal
                or job.source_job_id != candidate.source_job_id
                or job.canonical_url != candidate.original_url
                or job.company_name != candidate.company_name
                or job.title != candidate.title
                or job.location_text != candidate.location_text
                or job.description_hash != description_hash
                or job.cross_source_signature != signature
            )
            if material_changed:
                job.source_type = candidate.portal
                job.source_job_id = candidate.source_job_id
                job.canonical_url = candidate.original_url
                job.company_name = candidate.company_name
                job.title = candidate.title
                job.normalized_title = normalize_identity_text(candidate.title)
                job.location_text = candidate.location_text
                job.description = candidate.snippet
                job.description_hash = description_hash
                job.dedupe_signature = _portal_dedupe_signature(
                    candidate,
                    description_hash,
                )
                job.cross_source_signature = signature
                job.updated_at = observed_at
        job.last_seen_at = self._latest(job.last_seen_at, observed_at)
        job.updated_at = observed_at
        return PortalJobUpsertResult(
            job=job,
            source=source,
            job_created=False,
            source_created=False,
            materially_changed=material_changed or source_changed,
        )

    @staticmethod
    def _normalize(candidate: PortalJobCandidate) -> PortalJobCandidate:
        portal = candidate.portal.strip().casefold()
        source_job_id = normalize_display_text(candidate.source_job_id)
        title = normalize_display_text(candidate.title)
        company_name = normalize_display_text(candidate.company_name)
        location = normalize_display_text(candidate.location_text)
        snippet = _normalize_snippet(candidate.snippet)
        try:
            original_url = normalize_job_url(candidate.original_url)
        except (TypeError, ValueError) as error:
            raise PortalJobPersistenceError("Portal job URL is invalid") from error

        if portal not in PORTAL_NAMES or candidate.data_completeness != "partial":
            raise PortalJobPersistenceError("Portal candidate type is invalid")
        if (
            not source_job_id
            or len(source_job_id) > 255
            or _has_control_character(source_job_id)
        ):
            raise PortalJobPersistenceError("Portal source job identifier is invalid")
        if not title or len(title) > 1_000:
            raise PortalJobPersistenceError("Portal job title is invalid")
        if not company_name or len(company_name) > 160:
            raise PortalJobPersistenceError("Portal company name is invalid")
        if len(location) > 1_000 or len(snippet) > MAX_PORTAL_SNIPPET_CHARS:
            raise PortalJobPersistenceError("Portal metadata exceeds its limit")

        return PortalJobCandidate(
            portal=portal,
            source_job_id=source_job_id,
            original_url=original_url,
            title=title,
            company_name=company_name,
            location_text=location,
            snippet=snippet,
        )

    @staticmethod
    def _observed_at(value: datetime | None) -> datetime:
        observed_at = value or utc_now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("Portal observation timestamp must include a timezone")
        return observed_at.astimezone(timezone.utc)

    @staticmethod
    def _latest(current: datetime, observed: datetime) -> datetime:
        if current.tzinfo is None or current.utcoffset() is None:
            current = current.replace(tzinfo=timezone.utc)
        return max(current.astimezone(timezone.utc), observed)


def _normalize_snippet(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split())


def _has_control_character(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _portal_dedupe_signature(
    candidate: PortalJobCandidate,
    description_hash: str,
) -> str:
    return _hash_text(
        "\0".join(
            (
                candidate.portal,
                candidate.source_job_id,
                normalize_identity_text(candidate.title),
                normalize_identity_text(candidate.location_text),
                description_hash,
            )
        )
    )
