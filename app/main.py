import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.db import create_database_engine, create_session_factory, database_is_ready, run_migrations
from app.providers.telegram import open_telegram_client
from app.services.companies import CompanyService
from app.services.notifications import NotificationService
from app.services.runtime_settings import RuntimeSettingsService
from app.services.scan_history import ScanHistoryService
from app.services.scans import ApplicationScanPipeline, ScanController
from app.tasks.scheduler import ScanScheduler
from app.web.companies import router as companies_router
from app.web.jobs import router as jobs_router
from app.web.profiles import router as profiles_router
from app.web.routes import STATIC_DIR, router
from app.web.scans import router as scans_router
from app.web.settings import router as settings_router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=resolved_settings.log_level)
        run_migrations(resolved_settings)
        engine = create_database_engine(resolved_settings.database_url)
        if not database_is_ready(engine):
            engine.dispose()
            raise RuntimeError("Database readiness check failed")
        application.state.engine = engine
        application.state.session_factory = create_session_factory(engine)
        application.state.backup_lock = asyncio.Lock()
        try:
            runtime_settings = RuntimeSettingsService(
                application.state.session_factory
            ).load(resolved_settings)
            application.state.settings = runtime_settings
            scan_history = ScanHistoryService(application.state.session_factory)
            scan_history.recover_interrupted_runs()
            initial_scan_snapshot = scan_history.latest_snapshot()
            application.state.scan_history = scan_history
            with application.state.session_factory() as session:
                CompanyService(session).import_seed_file(runtime_settings.company_seed_path)
            async with open_telegram_client(runtime_settings) as telegram_client:
                notification_service = NotificationService(
                    application.state.session_factory,
                    telegram_client,
                    match_threshold=runtime_settings.telegram_match_threshold,
                )
                scan_controller = ScanController(
                    ApplicationScanPipeline(
                        application.state.session_factory,
                        runtime_settings,
                        recommendation_notifier=notification_service,
                    ),
                    completion_notifier=notification_service,
                    history_writer=scan_history,
                    initial_snapshot=initial_scan_snapshot,
                )
                scan_scheduler = ScanScheduler(
                    scan_controller,
                    interval_hours=runtime_settings.scan_interval_hours,
                )
                application.state.notification_service = notification_service
                application.state.scan_controller = scan_controller
                application.state.scan_scheduler = scan_scheduler
                try:
                    scan_scheduler.start()
                    yield
                finally:
                    scan_scheduler.shutdown()
                    await scan_controller.shutdown()
        finally:
            engine.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.base_settings = resolved_settings
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    application.include_router(router)
    application.include_router(profiles_router)
    application.include_router(companies_router)
    application.include_router(jobs_router)
    application.include_router(settings_router)
    application.include_router(scans_router)
    return application


app = create_app()
