from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.jobs import Job


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
