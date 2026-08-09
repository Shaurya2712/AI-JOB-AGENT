import json

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.providers.search.base import (
    SearchProviderError,
    SearchProviderNotConfigured,
    WebSearchProvider,
    WebSearchResult,
)


BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_RESPONSE_BYTES = 1024 * 1024


class _BraveResult(BaseModel):
    title: str = Field(max_length=1000)
    url: str = Field(max_length=4000)
    description: str = Field(default="", max_length=10_000)


class _BraveWebResults(BaseModel):
    results: list[_BraveResult] = Field(default_factory=list)


class _BraveResponse(BaseModel):
    web: _BraveWebResults | None = None


class BraveSearchProvider(WebSearchProvider):
    name = "brave"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str | None,
        country: str,
        language: str,
        results_per_query: int,
    ) -> None:
        self.client = client
        self.api_key = (api_key or "").strip()
        self.country = country
        self.language = language
        self.results_per_query = results_per_query

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str) -> list[WebSearchResult]:
        if not self.is_configured:
            raise SearchProviderNotConfigured("Brave Search is not configured")

        cleaned_query = " ".join(query.split())
        if not cleaned_query or len(cleaned_query) > 400 or len(cleaned_query.split()) > 50:
            raise SearchProviderError("Search query exceeds Brave Search limits")

        payload = await self._request_with_one_safe_retry(cleaned_query)
        try:
            parsed = _BraveResponse.model_validate(json.loads(payload))
        except (json.JSONDecodeError, ValidationError) as error:
            raise SearchProviderError("Brave Search returned an invalid response") from error

        if parsed.web is None:
            return []
        return [
            WebSearchResult(title=item.title, url=item.url, description=item.description)
            for item in parsed.web.results[: self.results_per_query]
        ]

    async def _request_with_one_safe_retry(self, query: str) -> bytes:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with self.client.stream(
                    "GET",
                    BRAVE_WEB_SEARCH_URL,
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": self.api_key,
                    },
                    params={
                        "q": query,
                        "count": self.results_per_query,
                        "country": self.country,
                        "search_lang": self.language,
                    },
                ) as response:
                    if response.status_code >= 500 and attempt == 0:
                        continue
                    if response.is_error:
                        raise SearchProviderError(
                            f"Brave Search request failed with HTTP {response.status_code}"
                        )

                    content_length = response.headers.get("content-length")
                    if (
                        content_length
                        and content_length.isdigit()
                        and int(content_length) > MAX_RESPONSE_BYTES
                    ):
                        raise SearchProviderError("Brave Search response exceeds the 1 MiB limit")

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise SearchProviderError("Brave Search response exceeds the 1 MiB limit")
                    return bytes(body)
            except SearchProviderError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
                if attempt == 1:
                    break

        raise SearchProviderError("Brave Search request failed") from last_error
