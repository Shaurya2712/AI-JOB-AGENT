from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.config import Settings
from app.providers.jobs.greenhouse import GreenhouseConnector
from app.providers.jobs.lever import LeverConnector


@asynccontextmanager
async def open_greenhouse_connector(settings: Settings) -> AsyncIterator[GreenhouseConnector]:
    limits = httpx.Limits(
        max_connections=settings.job_source_concurrency,
        max_keepalive_connections=settings.job_source_concurrency,
    )
    timeout = httpx.Timeout(settings.job_source_timeout_seconds)
    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=False) as client:
        yield GreenhouseConnector(
            client,
            max_response_bytes=settings.job_source_max_response_bytes,
        )


@asynccontextmanager
async def open_lever_connector(settings: Settings) -> AsyncIterator[LeverConnector]:
    limits = httpx.Limits(
        max_connections=settings.job_source_concurrency,
        max_keepalive_connections=settings.job_source_concurrency,
    )
    timeout = httpx.Timeout(settings.job_source_timeout_seconds)
    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=False) as client:
        yield LeverConnector(
            client,
            max_response_bytes=settings.job_source_max_response_bytes,
        )
