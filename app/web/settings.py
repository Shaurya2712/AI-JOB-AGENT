from pathlib import Path
import shutil
from tempfile import mkdtemp

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.services.backups import BackupError, BackupService, MAX_ARCHIVE_BYTES
from app.services.notifications import (
    DestinationInputError,
    NotificationDestinationService,
)
from app.services.runtime_settings import RuntimeSettingsService
from app.web.dependencies import get_session
from app.web.routes import TEMPLATES_DIR


router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _backup_context(
    request: Request,
    *,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "request": request,
        "app_name": request.app.state.settings.app_name,
        "active_nav": "settings",
        "backup_error": error,
        "restored": request.query_params.get("restored") == "1",
        "max_archive_mib": MAX_ARCHIVE_BYTES // (1024 * 1024),
    }


def _backup_service(request: Request) -> BackupService:
    return BackupService(
        request.app.state.settings,
        request.app.state.engine,
        RuntimeSettingsService(request.app.state.session_factory),
    )


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


@router.get("/backup", response_class=HTMLResponse, name="backup_settings")
def backup_settings(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="backup_settings.html",
        context=_backup_context(request),
    )


@router.post("/backup/export", name="export_backup")
async def export_backup(request: Request) -> Response:
    async with request.app.state.backup_lock:
        try:
            artifact = await run_in_threadpool(_backup_service(request).create_archive)
        except BackupError as error:
            return templates.TemplateResponse(
                request=request,
                name="backup_settings.html",
                context=_backup_context(request, error=str(error)),
                status_code=422,
            )
    return FileResponse(
        artifact.archive_path,
        media_type="application/zip",
        filename=artifact.filename,
        background=BackgroundTask(artifact.cleanup),
    )


@router.post("/backup/restore", name="restore_backup")
async def restore_backup(request: Request) -> Response:
    form = await request.form()
    upload = form.get("backup_file")
    if form.get("confirm") != "replace":
        if isinstance(upload, UploadFile):
            await upload.close()
        return templates.TemplateResponse(
            request=request,
            name="backup_settings.html",
            context=_backup_context(
                request,
                error="Confirm that restore may replace current local data",
            ),
            status_code=422,
        )
    if not isinstance(upload, UploadFile) or not upload.filename:
        return templates.TemplateResponse(
            request=request,
            name="backup_settings.html",
            context=_backup_context(request, error="Choose a Job Agent backup archive"),
            status_code=422,
        )

    workspace = Path(mkdtemp(prefix="job-agent-restore-upload-"))
    uploaded_archive = workspace / "backup.zip"
    try:
        written = 0
        with uploaded_archive.open("wb") as destination:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_ARCHIVE_BYTES:
                    raise BackupError("Backup archive exceeds the upload safety limit")
                destination.write(chunk)
        if written == 0:
            raise BackupError("Backup archive is empty")

        async with request.app.state.backup_lock:
            scheduler = request.app.state.scan_scheduler
            controller = request.app.state.scan_controller
            scheduler.pause()
            suspended = await controller.suspend_if_idle()
            if not suspended:
                scheduler.resume()
                raise BackupError("Wait for the current scan to finish before restoring")
            try:
                await run_in_threadpool(
                    _backup_service(request).restore_archive,
                    uploaded_archive,
                )
                request.app.state.settings = RuntimeSettingsService(
                    request.app.state.session_factory
                ).load(request.app.state.base_settings)
            finally:
                await controller.resume()
                scheduler.resume()
    except BackupError as error:
        return templates.TemplateResponse(
            request=request,
            name="backup_settings.html",
            context=_backup_context(request, error=str(error)),
            status_code=422,
        )
    finally:
        await upload.close()
        shutil.rmtree(workspace, ignore_errors=True)
    return RedirectResponse(url="/settings/backup?restored=1", status_code=303)


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
