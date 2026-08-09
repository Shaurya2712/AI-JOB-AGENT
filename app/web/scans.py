from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.web.routes import TEMPLATES_DIR


router = APIRouter(prefix="/scans", tags=["scans"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("", response_class=HTMLResponse, name="scan_history")
def scan_history(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="scans.html",
        context={
            "app_name": request.app.state.settings.app_name,
            "active_nav": "scans",
            "health": request.app.state.scan_history.recent_health(),
            "current_run": request.app.state.scan_controller.snapshot(),
        },
    )
