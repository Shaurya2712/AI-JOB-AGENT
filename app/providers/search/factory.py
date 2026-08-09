from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import httpx

from app.config import Settings
from app.providers.search.base import DisabledSearchProvider, WebSearchProvider
from app.providers.search.brave import BraveSearchProvider


@asynccontextmanager
async def open_search_provider(settings: Settings) -> AsyncIterator[WebSearchProvider]:
    if settings.search_provider == "disabled":
        yield DisabledSearchProvider()
        return

    limits = httpx.Limits(max_connections=5, max_keepalive_connections=3)
    timeout = httpx.Timeout(settings.search_timeout_seconds)
    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=False) as client:
        secret = settings.brave_search_api_key
        yield BraveSearchProvider(
            client,
            api_key=secret.get_secret_value() if secret else None,
            country=settings.search_country,
            language=settings.search_language,
            results_per_query=settings.search_results_per_query,
        )
