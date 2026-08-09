from urllib.parse import quote

import httpx

from app.providers.ai._http import post_bounded_json
from app.providers.ai.base import (
    AIProvider,
    AIProviderNotConfigured,
    AIProviderRequest,
    AIProviderResponseError,
    parse_match_output_text,
)
from app.schemas.ai import AIMatchOutput


GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiAIProvider(AIProvider):
    name = "gemini"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str | None,
        model: str,
    ) -> None:
        self.client = client
        self.api_key = (api_key or "").strip()
        self.model = model.strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)

    async def score_match(self, request: AIProviderRequest) -> AIMatchOutput:
        if not self.is_configured:
            raise AIProviderNotConfigured("Gemini is not configured")
        response = await post_bounded_json(
            self.client,
            provider_name="Gemini",
            url=f"{GEMINI_API_ROOT}/{quote(self.model, safe='')}:generateContent",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            payload={
                "systemInstruction": {"parts": [{"text": request.system_prompt}]},
                "contents": [
                    {"role": "user", "parts": [{"text": request.user_prompt}]}
                ],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": AIMatchOutput.model_json_schema(),
                },
            },
        )
        candidates = response.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content")
                if not isinstance(content, dict) or not isinstance(content.get("parts"), list):
                    continue
                for part in content["parts"]:
                    if isinstance(part, dict) and "text" in part:
                        return parse_match_output_text(part["text"])
        raise AIProviderResponseError("Gemini returned no structured match")
