from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.config import Settings
from app.providers.jobs.ashby import AshbyConnector
from app.providers.jobs.greenhouse import GreenhouseConnector
from app.providers.jobs.generic import GenericCareerPageConnector
from app.providers.jobs.lever import LeverConnector
from app.providers.jobs.workday import WorkdayConnector


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


@asynccontextmanager
async def open_ashby_connector(settings: Settings) -> AsyncIterator[AshbyConnector]:
    limits = httpx.Limits(
        max_connections=settings.job_source_concurrency,
        max_keepalive_connections=settings.job_source_concurrency,
    )
    timeout = httpx.Timeout(settings.job_source_timeout_seconds)
    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=False) as client:
        yield AshbyConnector(
            client,
            max_response_bytes=settings.job_source_max_response_bytes,
        )


@asynccontextmanager
async def open_workday_connector(settings: Settings) -> AsyncIterator[WorkdayConnector]:
    limits = httpx.Limits(
        max_connections=settings.job_source_concurrency,
        max_keepalive_connections=settings.job_source_concurrency,
    )
    timeout = httpx.Timeout(settings.job_source_timeout_seconds)
    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=False) as client:
        yield WorkdayConnector(
            client,
            max_response_bytes=settings.job_source_max_response_bytes,
            request_concurrency=settings.job_source_concurrency,
        )


@asynccontextmanager
async def open_generic_career_page_connector(
    settings: Settings,
) -> AsyncIterator[GenericCareerPageConnector]:
    limits = httpx.Limits(
        max_connections=settings.job_source_concurrency,
        max_keepalive_connections=settings.job_source_concurrency,
    )
    timeout = httpx.Timeout(settings.job_source_timeout_seconds)
    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=False) as client:
        yield GenericCareerPageConnector(
            client,
            max_response_bytes=settings.job_source_max_response_bytes,
            request_concurrency=settings.job_source_concurrency,
        )
