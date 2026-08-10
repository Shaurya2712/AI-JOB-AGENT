import json

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.providers.search.base import (
    SearchProviderError,
    SearchProviderNotConfigured,
    WebSearchProvider,
    WebSearchResult,
)


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_RESPONSE_BYTES = 1024 * 1024


class _TavilyResult(BaseModel):
    title: str = Field(max_length=1000)
    url: str = Field(max_length=4000)
    content: str = Field(default="", max_length=10_000)


class _TavilyResponse(BaseModel):
    results: list[_TavilyResult] = Field(default_factory=list)


class TavilySearchProvider(WebSearchProvider):
    name = "tavily"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str | None,
        results_per_query: int,
    ) -> None:
        self.client = client
        self.api_key = (api_key or "").strip()
        self.results_per_query = results_per_query

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str) -> list[WebSearchResult]:
        if not self.is_configured:
            raise SearchProviderNotConfigured("Tavily Search is not configured")

        cleaned_query = " ".join(query.split())
        if not cleaned_query or len(cleaned_query) > 400 or len(cleaned_query.split()) > 50:
            raise SearchProviderError("Search query exceeds Tavily Search limits")

        payload = await self._request_with_one_safe_retry(cleaned_query)
        try:
            parsed = _TavilyResponse.model_validate(json.loads(payload))
        except (json.JSONDecodeError, ValidationError) as error:
            raise SearchProviderError("Tavily Search returned an invalid response") from error

        return [
            WebSearchResult(title=item.title, url=item.url, description=item.content)
            for item in parsed.results[: self.results_per_query]
        ]

    async def _request_with_one_safe_retry(self, query: str) -> bytes:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with self.client.stream(
                    "POST",
                    TAVILY_SEARCH_URL,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "search_depth": "basic",
                        "topic": "general",
                        "include_answer": False,
                        "include_raw_content": False,
                        "max_results": self.results_per_query,
                        "auto_parameters": False,
                    },
                ) as response:
                    if response.status_code >= 500 and attempt == 0:
                        continue
                    if response.is_error:
                        raise SearchProviderError(
                            f"Tavily Search request failed with HTTP {response.status_code}"
                        )

                    content_length = response.headers.get("content-length")
                    if (
                        content_length
                        and content_length.isdigit()
                        and int(content_length) > MAX_RESPONSE_BYTES
                    ):
                        raise SearchProviderError("Tavily Search response exceeds the 1 MiB limit")

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise SearchProviderError(
                                "Tavily Search response exceeds the 1 MiB limit"
                            )
                    return bytes(body)
            except SearchProviderError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
                if attempt == 1:
                    break

        raise SearchProviderError("Tavily Search request failed") from last_error
