from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.services.notifications import (
    DestinationInputError,
    NotificationDestinationService,
)
from app.web.dependencies import get_session
from app.web.routes import TEMPLATES_DIR


router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/notifications", response_class=HTMLResponse, name="notification_settings")
def notification_settings(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    settings = request.app.state.settings
    return templates.TemplateResponse(
        request=request,
        name="notification_settings.html",
        context={
            "app_name": settings.app_name,
            "active_nav": "settings",
            "destinations": NotificationDestinationService(
                session
            ).list_destinations(),
            "telegram_configured": settings.telegram_bot_token is not None
            and bool(settings.telegram_bot_token.get_secret_value().strip()),
            "match_threshold": settings.telegram_match_threshold,
            "saved": request.query_params.get("saved") == "1",
        },
    )


@router.post("/notifications", name="save_notification_settings")
async def save_notification_settings(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    form = await request.form()
    try:
        NotificationDestinationService(session).configure(
            str(form.get("destination_type", "")),
            name=str(form.get("name", "")),
            telegram_chat_id=str(form.get("telegram_chat_id", "")),
            is_enabled=form.get("is_enabled") is not None,
        )
    except DestinationInputError as error:
        return HTMLResponse(str(error), status_code=422)
    return RedirectResponse(url="/settings/notifications?saved=1", status_code=303)
