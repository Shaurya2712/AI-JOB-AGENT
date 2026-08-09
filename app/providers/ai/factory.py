from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.config import Settings
from app.providers.ai.anthropic import AnthropicAIProvider
from app.providers.ai.base import AIProvider, DisabledAIProvider
from app.providers.ai.gemini import GeminiAIProvider
from app.providers.ai.openai import OpenAIProvider


def create_ai_provider(
    settings: Settings,
    client: httpx.AsyncClient,
) -> AIProvider:
    if settings.ai_provider == "disabled":
        return DisabledAIProvider()

    secret_by_provider = {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "gemini": settings.gemini_api_key,
    }
    secret = secret_by_provider[settings.ai_provider]
    api_key = secret.get_secret_value() if secret else None
    if settings.ai_provider == "openai":
        return OpenAIProvider(
            client,
            api_key=api_key,
            model=settings.ai_model,
        )
    if settings.ai_provider == "anthropic":
        return AnthropicAIProvider(
            client,
            api_key=api_key,
            model=settings.ai_model,
        )
    return GeminiAIProvider(
        client,
        api_key=api_key,
        model=settings.ai_model,
    )


@asynccontextmanager
async def open_ai_provider(settings: Settings) -> AsyncIterator[AIProvider]:
    limits = httpx.Limits(
        max_connections=settings.ai_concurrency,
        max_keepalive_connections=settings.ai_concurrency,
    )
    timeout = httpx.Timeout(settings.ai_timeout_seconds)
    async with httpx.AsyncClient(
        limits=limits,
        timeout=timeout,
        follow_redirects=False,
    ) as client:
        yield create_ai_provider(settings, client)
