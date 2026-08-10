from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BeforeValidator
from sqlalchemy.orm import Session

from app.services.job_dashboard import JobDashboardService, JobFilters
from app.services.job_details import (
    JobDetailNotFoundError,
    JobDetailService,
    JobStateInputError,
)
from app.web.dependencies import get_session
from app.web.routes import TEMPLATES_DIR


router = APIRouter(prefix="/jobs", tags=["jobs"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _empty_query_value_to_none(value: object) -> object | None:
    return None if value == "" else value


@router.get("", response_class=HTMLResponse, name="jobs")
def jobs(
    request: Request,
    profile_id: Annotated[
        int | None,
        Query(gt=0),
        BeforeValidator(_empty_query_value_to_none),
    ] = None,
    role: Annotated[str, Query(max_length=120)] = "",
    min_score: Annotated[
        int | None,
        Query(ge=0, le=100),
        BeforeValidator(_empty_query_value_to_none),
    ] = None,
    location_mode: Annotated[str, Query(max_length=30)] = "",
    city: Annotated[str, Query(max_length=160)] = "",
    source: Annotated[str, Query(max_length=40)] = "",
    lifecycle: Annotated[str, Query(max_length=20)] = "open",
    state: Annotated[str, Query(max_length=10)] = "",
    minimum_salary: Annotated[
        Decimal | None,
        Query(ge=0),
        BeforeValidator(_empty_query_value_to_none),
    ] = None,
    remote: bool = False,
    posted_after: Annotated[
        date | None,
        BeforeValidator(_empty_query_value_to_none),
    ] = None,
    discovered_after: Annotated[
        date | None,
        BeforeValidator(_empty_query_value_to_none),
    ] = None,
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


@router.get("/{job_id}", response_class=HTMLResponse, name="job_detail")
def job_detail(
    job_id: int,
    request: Request,
    profile_id: Annotated[int | None, Query(gt=0)] = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    try:
        detail = JobDetailService(session).get_detail(
            job_id,
            profile_id=profile_id,
        )
    except JobDetailNotFoundError:
        return HTMLResponse("Job or profile not found", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="job_detail.html",
        context={
            "app_name": request.app.state.settings.app_name,
            "active_nav": "jobs",
            "detail": detail,
        },
    )


@router.post("/{job_id}/state", name="set_job_state")
async def set_job_state(
    job_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    form = await request.form()
    try:
        profile_id = int(str(form.get("profile_id", "")))
        resume_value = str(form.get("resume_id", "")).strip()
        resume_id = int(resume_value) if resume_value else None
    except ValueError:
        return HTMLResponse("Invalid profile or resume", status_code=422)
    action = str(form.get("action", ""))
    note = str(form.get("note", ""))
    if profile_id <= 0 or (resume_id is not None and resume_id <= 0):
        return HTMLResponse("Invalid profile or resume", status_code=422)
    try:
        state = JobDetailService(session).set_state(
            job_id,
            profile_id,
            action,
            resume_id=resume_id,
            note=note,
        )
    except JobDetailNotFoundError:
        return HTMLResponse("Job or profile not found", status_code=404)
    except JobStateInputError as error:
        return HTMLResponse(str(error), status_code=422)
    if state.state == "applied":
        try:
            await request.app.state.notification_service.notify_application(
                job_id,
                profile_id,
            )
        except Exception:
            pass
    return RedirectResponse(
        url=f"/jobs/{job_id}?profile_id={profile_id}",
        status_code=303,
    )
