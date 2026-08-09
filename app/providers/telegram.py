from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.config import Settings


TELEGRAM_API_ROOT = "https://api.telegram.org"
TELEGRAM_MESSAGE_LIMIT = 4096


class TelegramDeliveryError(RuntimeError):
    pass


class TelegramClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        bot_token: str | None,
    ) -> None:
        self._client = client
        self._bot_token = bot_token.strip() if bot_token else ""

    @property
    def is_configured(self) -> bool:
        return bool(self._bot_token)

    async def send_message(self, chat_id: str, text: str) -> None:
        if not self.is_configured:
            raise TelegramDeliveryError("Telegram bot is not configured")
        try:
            response = await self._client.post(
                f"{TELEGRAM_API_ROOT}/bot{self._bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text[:TELEGRAM_MESSAGE_LIMIT],
                    "disable_web_page_preview": True,
                },
            )
            if response.status_code < 200 or response.status_code >= 300:
                raise TelegramDeliveryError("Telegram rejected the message")
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise TelegramDeliveryError("Telegram rejected the message")
        except TelegramDeliveryError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise TelegramDeliveryError("Telegram delivery failed") from error


@asynccontextmanager
async def open_telegram_client(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[TelegramClient]:
    token = (
        settings.telegram_bot_token.get_secret_value()
        if settings.telegram_bot_token is not None
        else None
    )
    limits = httpx.Limits(max_connections=2, max_keepalive_connections=1)
    async with httpx.AsyncClient(
        timeout=settings.telegram_timeout_seconds,
        limits=limits,
        follow_redirects=False,
        transport=transport,
    ) as client:
        yield TelegramClient(client, token)
