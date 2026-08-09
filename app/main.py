from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.db import create_database_engine, create_session_factory, database_is_ready, run_migrations
from app.services.companies import CompanyService
from app.web.companies import router as companies_router
from app.web.profiles import router as profiles_router
from app.web.routes import STATIC_DIR, router


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
        try:
            with application.state.session_factory() as session:
                CompanyService(session).import_seed_file(resolved_settings.company_seed_path)
            yield
        finally:
            engine.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    application.include_router(router)
    application.include_router(profiles_router)
    application.include_router(companies_router)
    return application


app = create_app()
