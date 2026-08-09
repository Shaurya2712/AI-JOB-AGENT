from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.job_user_state import JobUserState
from app.models.jobs import Job
from app.models.profiles import CandidateProfile
from app.models.resumes import Resume


MAX_APPLICATION_NOTE_CHARS = 5_000
USER_STATES = frozenset({"saved", "applied", "ignored"})


class JobDetailNotFoundError(LookupError):
    pass


class JobStateInputError(ValueError):
    pass


@dataclass(frozen=True)
class JobDetailView:
    job: Job
    company: Company
    profiles: tuple[CandidateProfile, ...]
    profile: CandidateProfile | None
    match: JobMatch | None
    user_state: JobUserState | None
    resumes: tuple[Resume, ...]
    suggested_resume: Resume | None
    salary_text: str
    experience_text: str
    posted_date: str
    discovered_date: str

    @property
    def state_name(self) -> str:
        return self.user_state.state if self.user_state is not None else "new"


class JobDetailService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_detail(
        self,
        job_id: int,
        *,
        profile_id: int | None = None,
    ) -> JobDetailView:
        job = self.session.get(Job, job_id)
        if job is None:
            raise JobDetailNotFoundError(f"Job {job_id} was not found")
        company = self.session.get(Company, job.company_id)
        if company is None:
            raise JobDetailNotFoundError(f"Company for job {job_id} was not found")

        profiles = tuple(
            self.session.scalars(
                select(CandidateProfile).order_by(
                    CandidateProfile.is_active.desc(),
                    CandidateProfile.name,
                    CandidateProfile.id,
                )
            )
        )
        profile = self._selected_profile(job.id, profiles, profile_id)
        match: JobMatch | None = None
        user_state: JobUserState | None = None
        resumes: tuple[Resume, ...] = ()
        suggested_resume: Resume | None = None
        if profile is not None:
            match = self.session.scalar(
                select(JobMatch).where(
                    JobMatch.job_id == job.id,
                    JobMatch.profile_id == profile.id,
                )
            )
            user_state = self.session.scalar(
                select(JobUserState).where(
                    JobUserState.job_id == job.id,
                    JobUserState.profile_id == profile.id,
                )
            )
            resumes = tuple(
                self.session.scalars(
                    select(Resume)
                    .where(Resume.profile_id == profile.id)
                    .order_by(Resume.is_primary.desc(), Resume.name, Resume.id)
                    .limit(100)
                )
            )
            if match is not None and match.suggested_resume_id is not None:
                suggested_resume = next(
                    (
                        resume
                        for resume in resumes
                        if resume.id == match.suggested_resume_id
                    ),
                    None,
                )

        return JobDetailView(
            job=job,
            company=company,
            profiles=profiles,
            profile=profile,
            match=match,
            user_state=user_state,
            resumes=resumes,
            suggested_resume=suggested_resume,
            salary_text=_salary_text(job),
            experience_text=_experience_text(job),
            posted_date=_date_text(job.posted_at),
            discovered_date=_date_text(job.discovered_at),
        )

    def set_state(
        self,
        job_id: int,
        profile_id: int,
        state: str,
        *,
        resume_id: int | None = None,
        note: str = "",
    ) -> JobUserState:
        normalized_state = state.strip().casefold()
        normalized_note = note.strip()
        if normalized_state not in USER_STATES:
            raise JobStateInputError("Unknown job state")
        if len(normalized_note) > MAX_APPLICATION_NOTE_CHARS:
            raise JobStateInputError("Application note is too long")
        if self.session.get(Job, job_id) is None:
            raise JobDetailNotFoundError(f"Job {job_id} was not found")
        if self.session.get(CandidateProfile, profile_id) is None:
            raise JobDetailNotFoundError(f"Profile {profile_id} was not found")

        selected_resume: Resume | None = None
        if normalized_state == "applied" and resume_id is not None:
            selected_resume = self.session.scalar(
                select(Resume).where(
                    Resume.id == resume_id,
                    Resume.profile_id == profile_id,
                )
            )
            if selected_resume is None:
                raise JobStateInputError("Selected resume does not belong to this profile")

        user_state = self.session.scalar(
            select(JobUserState).where(
                JobUserState.job_id == job_id,
                JobUserState.profile_id == profile_id,
            )
        )
        now = utc_now()
        if user_state is None:
            user_state = JobUserState(
                job_id=job_id,
                profile_id=profile_id,
                state=normalized_state,
                updated_at=now,
            )
            self.session.add(user_state)
        else:
            user_state.state = normalized_state
            user_state.updated_at = now

        if normalized_state == "applied":
            user_state.applied_at = user_state.applied_at or now
            user_state.resume_id = selected_resume.id if selected_resume is not None else None
            user_state.note = normalized_note or None

        try:
            self.session.commit()
            self.session.refresh(user_state)
        except Exception:
            self.session.rollback()
            raise
        return user_state

    def _selected_profile(
        self,
        job_id: int,
        profiles: tuple[CandidateProfile, ...],
        requested_profile_id: int | None,
    ) -> CandidateProfile | None:
        if requested_profile_id is not None:
            profile = next(
                (item for item in profiles if item.id == requested_profile_id),
                None,
            )
            if profile is None:
                raise JobDetailNotFoundError(
                    f"Profile {requested_profile_id} was not found"
                )
            return profile

        best_profile_id = self.session.scalar(
            select(JobMatch.profile_id)
            .join(CandidateProfile, CandidateProfile.id == JobMatch.profile_id)
            .where(JobMatch.job_id == job_id)
            .order_by(
                CandidateProfile.is_active.desc(),
                JobMatch.overall_score.desc(),
                JobMatch.id,
            )
            .limit(1)
        )
        if best_profile_id is not None:
            return next(
                (item for item in profiles if item.id == best_profile_id),
                None,
            )
        return profiles[0] if profiles else None


def _salary_text(job: Job) -> str:
    if job.salary_min is None and job.salary_max is None:
        return "Not listed"
    currency = job.salary_currency or ""
    if job.salary_min is not None and job.salary_max is not None:
        value = f"{_amount(job.salary_min)}–{_amount(job.salary_max)}"
    else:
        amount = job.salary_min if job.salary_min is not None else job.salary_max
        value = _amount(amount)
    return f"{currency} {value}".strip()


def _amount(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _experience_text(job: Job) -> str:
    if job.experience_min is None and job.experience_max is None:
        return "Not listed"
    if job.experience_min is not None and job.experience_max is not None:
        return f"{job.experience_min:g}–{job.experience_max:g} years"
    value = job.experience_min if job.experience_min is not None else job.experience_max
    return f"{value:g} years" if value is not None else "Not listed"


def _date_text(value: datetime | None) -> str:
    return value.strftime("%d %b %Y") if value is not None else "Not listed"
