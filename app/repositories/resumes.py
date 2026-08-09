from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.resumes import Resume


class ResumeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def count_for_profile(self, profile_id: int) -> int:
        statement = select(func.count(Resume.id)).where(Resume.profile_id == profile_id)
        return self.session.scalar(statement) or 0

    def add(self, resume: Resume) -> None:
        self.session.add(resume)

    def get_for_profile(self, profile_id: int, resume_id: int) -> Resume | None:
        statement = select(Resume).where(Resume.id == resume_id, Resume.profile_id == profile_id)
        return self.session.scalar(statement)

    def clear_primary(self, profile_id: int) -> None:
        statement = (
            update(Resume)
            .where(Resume.profile_id == profile_id, Resume.is_primary.is_(True))
            .values(is_primary=False)
            .execution_options(synchronize_session=False)
        )
        self.session.execute(statement)

    def mark_primary(self, profile_id: int, resume_id: int) -> None:
        statement = (
            update(Resume)
            .where(Resume.id == resume_id, Resume.profile_id == profile_id)
            .values(is_primary=True)
            .execution_options(synchronize_session=False)
        )
        self.session.execute(statement)
