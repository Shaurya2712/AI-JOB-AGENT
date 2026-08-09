from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.services.job_dashboard import JobDashboardService, JobFilters
from app.web.dependencies import get_session
from app.web.routes import TEMPLATES_DIR


router = APIRouter(prefix="/jobs", tags=["jobs"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("", response_class=HTMLResponse, name="jobs")
def jobs(
    request: Request,
    profile_id: Annotated[int | None, Query(gt=0)] = None,
    role: Annotated[str, Query(max_length=120)] = "",
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    location_mode: Annotated[str, Query(max_length=30)] = "",
    city: Annotated[str, Query(max_length=160)] = "",
    source: Annotated[str, Query(max_length=40)] = "",
    lifecycle: Annotated[str, Query(max_length=20)] = "open",
    state: Annotated[str, Query(max_length=10)] = "",
    minimum_salary: Annotated[Decimal | None, Query(ge=0)] = None,
    remote: bool = False,
    posted_after: date | None = None,
    discovered_after: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    filters = JobFilters(
        profile_id=profile_id,
        role=" ".join(role.split()),
        min_score=min_score,
        location_mode=location_mode,
        city=" ".join(city.split()),
        source=source,
        lifecycle=lifecycle,
        state=state,
        minimum_salary=minimum_salary,
        remote_only=remote,
        posted_after=posted_after,
        discovered_after=discovered_after,
    )
    service = JobDashboardService(session)
    result = service.list_jobs(filters, page=page)
    return templates.TemplateResponse(
        request=request,
        name="jobs.html",
        context={
            "app_name": request.app.state.settings.app_name,
            "active_nav": "jobs",
            "filters": filters,
            "options": service.filter_options(),
            "result": result,
            "previous_url": (
                str(request.url.include_query_params(page=result.page - 1))
                if result.has_previous
                else None
            ),
            "next_url": (
                str(request.url.include_query_params(page=result.page + 1))
                if result.has_next
                else None
            ),
        },
    )
