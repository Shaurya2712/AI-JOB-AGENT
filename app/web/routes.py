from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import database_is_ready
from app.services.job_dashboard import JobDashboardService, JobFilters, STRONG_MATCH_MINIMUM
from app.web.dependencies import get_session


WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    settings = request.app.state.settings
    service = JobDashboardService(session)
    daily_queue = service.daily_action_queue(target=settings.daily_action_target)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": settings.app_name,
            "active_nav": "dashboard",
            "metrics": service.metrics(apply_today=daily_queue.count),
            "daily_queue": daily_queue,
            "strong_matches": service.list_jobs(
                JobFilters(
                    min_score=STRONG_MATCH_MINIMUM,
                    lifecycle="open",
                ),
                page=1,
            ).items[:5],
        },
    )


@router.get("/health", tags=["system"])
def health(request: Request) -> dict[str, str]:
    ready = database_is_ready(request.app.state.engine)
    return {
        "status": "ok" if ready else "unavailable",
        "database": "ok" if ready else "unavailable",
    }
