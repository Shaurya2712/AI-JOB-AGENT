from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job_matches import JobMatch


class JobMatchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, job_id: int, profile_id: int) -> JobMatch | None:
        statement = select(JobMatch).where(
            JobMatch.job_id == job_id,
            JobMatch.profile_id == profile_id,
        )
        return self.session.scalar(statement)

    def add(self, match: JobMatch) -> None:
        self.session.add(match)
