from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from math import ceil

from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.job_user_state import JobUserState
from app.models.jobs import Job
from app.models.profiles import CandidateProfile


JOBS_PER_PAGE = 25
STRONG_MATCH_MINIMUM = 85


@dataclass(frozen=True)
class JobFilters:
    profile_id: int | None = None
    role: str = ""
    min_score: int | None = None
    location_mode: str = ""
    city: str = ""
    source: str = ""
    lifecycle: str = "open"
    state: str = ""
    minimum_salary: Decimal | None = None
    remote_only: bool = False
    posted_after: date | None = None
    discovered_after: date | None = None


@dataclass(frozen=True)
class JobListItem:
    id: int
    title: str
    canonical_url: str
    company_name: str
    location_text: str
    remote_type: str | None
    salary_text: str
    source_type: str
    posted_date: str
    discovered_date: str
    lifecycle_status: str
    user_state: str
    overall_score: int | None
    recommendation_label: str | None
    profile_name: str | None


@dataclass(frozen=True)
class PaginatedJobs:
    items: tuple[JobListItem, ...]
    total: int
    page: int
    total_pages: int

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


@dataclass(frozen=True)
class ProfileFilterOption:
    id: int
    name: str
    is_active: bool


@dataclass(frozen=True)
class JobFilterOptions:
    profiles: tuple[ProfileFilterOption, ...]
    sources: tuple[str, ...]
    location_modes: tuple[str, ...]
    cities: tuple[str, ...]


@dataclass(frozen=True)
class DashboardMetrics:
    apply_today: int
    strong_matches: int
    new_jobs: int
    applied: int


@dataclass(frozen=True)
class DailyActionQueue:
    target: int
    items: tuple[JobListItem, ...]

    @property
    def count(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class _QueryParts:
    statement: Select[tuple[Job, Company, JobMatch | None, JobUserState | None, str | None]]
    match: type[JobMatch]
    user_state: type[JobUserState]


class JobDashboardService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_jobs(self, filters: JobFilters, *, page: int) -> PaginatedJobs:
        parts = self._query(filters)
        count_query = select(func.count()).select_from(
            parts.statement.with_only_columns(Job.id).order_by(None).subquery()
        )
        total = self.session.scalar(count_query) or 0
        total_pages = max(1, ceil(total / JOBS_PER_PAGE))
        page_number = min(max(1, page), total_pages)
        score_missing = case((parts.match.overall_score.is_(None), 1), else_=0)
        statement = (
            parts.statement.order_by(
                score_missing,
                parts.match.overall_score.desc(),
                Job.discovered_at.desc(),
                Job.id.desc(),
            )
            .limit(JOBS_PER_PAGE)
            .offset((page_number - 1) * JOBS_PER_PAGE)
        )
        items = tuple(
            self._item(job, company, match, user_state, profile_name)
            for job, company, match, user_state, profile_name in self.session.execute(
                statement
            )
        )
        return PaginatedJobs(
            items=items,
            total=total,
            page=page_number,
            total_pages=total_pages,
        )

    def filter_options(self) -> JobFilterOptions:
        profiles = tuple(
            ProfileFilterOption(profile.id, profile.name, profile.is_active)
            for profile in self.session.scalars(
                select(CandidateProfile).order_by(
                    CandidateProfile.is_active.desc(),
                    CandidateProfile.name,
                    CandidateProfile.id,
                )
            )
        )
        return JobFilterOptions(
            profiles=profiles,
            sources=self._distinct_strings(Job.source_type),
            location_modes=self._distinct_strings(Job.remote_type),
            cities=self._distinct_strings(Job.city),
        )

    def daily_action_queue(self, *, target: int) -> DailyActionQueue:
        queue_target = min(max(1, target), 100)
        parts = self._query(
            JobFilters(lifecycle="open"),
            active_profiles_only=True,
        )
        statement = (
            parts.statement.where(
                parts.match.id.is_not(None),
                ~exists(
                    select(JobUserState.id).where(
                        JobUserState.job_id == Job.id,
                        JobUserState.state.in_(("applied", "ignored")),
                    )
                ),
            )
            .order_by(
                parts.match.overall_score.desc(),
                Job.discovered_at.desc(),
                Job.id.desc(),
            )
            .limit(queue_target)
        )
        items = tuple(
            self._item(job, company, match, user_state, profile_name)
            for job, company, match, user_state, profile_name in self.session.execute(
                statement
            )
        )
        return DailyActionQueue(target=queue_target, items=items)

    def metrics(self, *, apply_today: int) -> DashboardMetrics:
        open_job = Job.lifecycle_status == "open"
        decisioned = exists(
            select(JobUserState.id).where(
                JobUserState.job_id == Job.id,
                JobUserState.state.in_(("saved", "applied", "ignored")),
            )
        )
        strong = self.session.scalar(
            select(func.count(func.distinct(Job.id)))
            .select_from(Job)
            .join(JobMatch, JobMatch.job_id == Job.id)
            .where(open_job, JobMatch.overall_score >= STRONG_MATCH_MINIMUM)
        ) or 0
        new_jobs = self.session.scalar(
            select(func.count(Job.id)).where(open_job, ~decisioned)
        ) or 0
        applied = self.session.scalar(
            select(func.count(func.distinct(JobUserState.job_id))).where(
                JobUserState.state == "applied"
            )
        ) or 0
        return DashboardMetrics(
            apply_today=apply_today,
            strong_matches=strong,
            new_jobs=new_jobs,
            applied=applied,
        )

    def _query(
        self,
        filters: JobFilters,
        *,
        active_profiles_only: bool = False,
    ) -> _QueryParts:
        match = aliased(JobMatch)
        user_state = aliased(JobUserState)
        match_id = select(JobMatch.id).where(JobMatch.job_id == Job.id)
        if active_profiles_only:
            match_id = match_id.join(
                CandidateProfile,
                CandidateProfile.id == JobMatch.profile_id,
            ).where(CandidateProfile.is_active.is_(True))
        if filters.profile_id is not None:
            match_id = match_id.where(JobMatch.profile_id == filters.profile_id)
        best_match_id = (
            match_id.order_by(JobMatch.overall_score.desc(), JobMatch.id)
            .limit(1)
            .correlate(Job)
            .scalar_subquery()
        )
        statement = (
            select(Job, Company, match, user_state, CandidateProfile.name)
            .join(Company, Company.id == Job.company_id)
            .outerjoin(match, match.id == best_match_id)
            .outerjoin(
                user_state,
                and_(
                    user_state.job_id == Job.id,
                    user_state.profile_id == match.profile_id,
                ),
            )
            .outerjoin(CandidateProfile, CandidateProfile.id == match.profile_id)
        )
        if filters.profile_id is not None:
            statement = statement.where(match.id.is_not(None))
        if filters.role:
            statement = statement.where(
                func.lower(Job.title).contains(filters.role.casefold(), autoescape=True)
            )
        if filters.min_score is not None:
            statement = statement.where(match.overall_score >= filters.min_score)
        if filters.location_mode:
            statement = statement.where(
                func.lower(Job.remote_type) == filters.location_mode.casefold()
            )
        if filters.city:
            statement = statement.where(
                func.lower(Job.city).contains(filters.city.casefold(), autoescape=True)
            )
        if filters.source:
            statement = statement.where(
                func.lower(Job.source_type) == filters.source.casefold()
            )
        if filters.lifecycle != "all":
            statement = statement.where(Job.lifecycle_status == filters.lifecycle)
        if filters.state == "new":
            statement = statement.where(
                or_(user_state.id.is_(None), user_state.state == "new")
            )
        elif filters.state in {"saved", "applied", "ignored"}:
            statement = statement.where(user_state.state == filters.state)
        if filters.minimum_salary is not None:
            statement = statement.where(
                func.coalesce(Job.salary_max, Job.salary_min) >= filters.minimum_salary
            )
        if filters.remote_only:
            statement = statement.where(func.lower(Job.remote_type) == "remote")
        if filters.posted_after is not None:
            statement = statement.where(
                Job.posted_at >= datetime.combine(filters.posted_after, time.min)
            )
        if filters.discovered_after is not None:
            statement = statement.where(
                Job.discovered_at
                >= datetime.combine(filters.discovered_after, time.min)
            )
        return _QueryParts(statement=statement, match=match, user_state=user_state)

    def _distinct_strings(self, column) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
        statement = (
            select(column)
            .where(column.is_not(None), column != "")
            .distinct()
            .order_by(column)
        )
        return tuple(self.session.scalars(statement))

    @staticmethod
    def _item(
        job: Job,
        company: Company,
        match: JobMatch | None,
        user_state: JobUserState | None,
        profile_name: str | None,
    ) -> JobListItem:
        return JobListItem(
            id=job.id,
            title=job.title,
            canonical_url=job.canonical_url,
            company_name=company.name,
            location_text=job.location_text or "Not listed",
            remote_type=job.remote_type,
            salary_text=_salary_text(job),
            source_type=job.source_type,
            posted_date=_date_text(job.posted_at),
            discovered_date=_date_text(job.discovered_at),
            lifecycle_status=job.lifecycle_status,
            user_state=user_state.state if user_state is not None else "new",
            overall_score=match.overall_score if match is not None else None,
            recommendation_label=(
                match.recommendation_label if match is not None else None
            ),
            profile_name=profile_name,
        )


def _salary_text(job: Job) -> str:
    if job.salary_min is None and job.salary_max is None:
        return "Not listed"
    currency = job.salary_currency or ""
    if job.salary_min is not None and job.salary_max is not None:
        amount = f"{_amount(job.salary_min)}–{_amount(job.salary_max)}"
    else:
        value = job.salary_min if job.salary_min is not None else job.salary_max
        amount = _amount(value)
    return f"{currency} {amount}".strip()


def _amount(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _date_text(value: datetime | None) -> str:
    return value.strftime("%d %b %Y") if value is not None else "Not listed"
