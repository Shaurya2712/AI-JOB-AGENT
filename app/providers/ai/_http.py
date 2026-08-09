import json

import httpx

from app.providers.ai.base import AIProviderError, AIProviderResponseError


MAX_AI_RESPONSE_BYTES = 1024 * 1024


async def post_bounded_json(
    client: httpx.AsyncClient,
    *,
    provider_name: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
) -> dict[str, object]:
    last_transport_error: Exception | None = None
    for attempt in range(2):
        try:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code >= 500 and attempt == 0:
                    continue
                if response.is_error:
                    raise AIProviderError(
                        f"{provider_name} request failed with HTTP {response.status_code}"
                    )

                content_length = response.headers.get("content-length")
                if (
                    content_length
                    and content_length.isdigit()
                    and int(content_length) > MAX_AI_RESPONSE_BYTES
                ):
                    raise AIProviderResponseError(
                        f"{provider_name} response exceeds the 1 MiB limit"
                    )

                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_AI_RESPONSE_BYTES:
                        raise AIProviderResponseError(
                            f"{provider_name} response exceeds the 1 MiB limit"
                        )
                try:
                    parsed = json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise AIProviderResponseError(
                        f"{provider_name} returned malformed JSON"
                    ) from error
                if not isinstance(parsed, dict):
                    raise AIProviderResponseError(
                        f"{provider_name} returned an invalid response envelope"
                    )
                return parsed
        except AIProviderError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as error:
            last_transport_error = error
            if attempt == 1:
                break

    raise AIProviderError(f"{provider_name} request failed") from last_transport_error
