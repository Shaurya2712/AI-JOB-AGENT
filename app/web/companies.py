from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.services.companies import CompanyService
from app.web.dependencies import get_session
from app.web.routes import TEMPLATES_DIR


router = APIRouter(prefix="/companies", tags=["companies"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("", response_class=HTMLResponse, name="companies")
def companies(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="companies.html",
        context={
            "app_name": request.app.state.settings.app_name,
            "active_nav": "companies",
            "companies": CompanyService(session).list_companies(),
        },
    )
