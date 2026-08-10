from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.jobs import Job
from app.models.portal_sources import PortalJobSource


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_match(
        self,
        company_id: int,
        *,
        source_type: str,
        source_job_id: str,
        canonical_url: str,
        dedupe_signature: str,
        allow_fallback: bool,
    ) -> Job | None:
        source_match = self.session.scalar(
            select(Job).where(
                Job.company_id == company_id,
                Job.source_type == source_type,
                Job.source_job_id == source_job_id,
            )
        )
        if source_match is not None:
            return source_match

        url_match = self.session.scalar(
            select(Job).where(
                Job.company_id == company_id,
                Job.canonical_url == canonical_url,
            )
        )
        if url_match is not None:
            return url_match

        if allow_fallback:
            return self.session.scalar(
                select(Job)
                .where(
                    Job.company_id == company_id,
                    Job.dedupe_signature == dedupe_signature,
                )
                .order_by(Job.id)
                .limit(1)
            )
        return None

    def add(self, job: Job) -> None:
        self.session.add(job)

    def find_cross_source_candidates(self, signature: str) -> list[Job]:
        statement = (
            select(Job)
            .where(Job.cross_source_signature == signature)
            .order_by(Job.id)
        )
        return list(self.session.scalars(statement).all())

    def find_unique_partial_cross_source_match(self, signature: str) -> Job | None:
        statement = (
            select(Job)
            .where(Job.cross_source_signature == signature)
            .order_by(Job.id)
            .limit(2)
        )
        matches = list(self.session.scalars(statement).all())
        if len(matches) != 1:
            return None
        match = matches[0]
        if match.company_id is not None or match.data_completeness != "partial":
            return None
        return match

    def find_portal_sources(
        self,
        portal_name: str,
        *,
        source_job_id: str,
        original_url: str,
    ) -> tuple[PortalJobSource | None, PortalJobSource | None]:
        identity_match = self.session.scalar(
            select(PortalJobSource).where(
                PortalJobSource.portal_name == portal_name,
                PortalJobSource.source_job_id == source_job_id,
            )
        )
        url_match = self.session.scalar(
            select(PortalJobSource).where(
                PortalJobSource.portal_name == portal_name,
                PortalJobSource.original_url == original_url,
            )
        )
        return identity_match, url_match

    def add_portal_source(self, source: PortalJobSource) -> None:
        self.session.add(source)

    def list_for_source(self, company_id: int, source_type: str) -> list[Job]:
        statement = (
            select(Job)
            .where(
                Job.company_id == company_id,
                Job.source_type == source_type,
            )
            .order_by(Job.id)
        )
        return list(self.session.scalars(statement).all())

    def get(self, job_id: int) -> Job | None:
        return self.session.get(Job, job_id)
