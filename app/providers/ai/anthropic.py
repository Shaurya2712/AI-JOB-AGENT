import httpx

from app.providers.ai._http import post_bounded_json
from app.providers.ai.base import (
    AIProvider,
    AIProviderNotConfigured,
    AIProviderRequest,
    AIProviderResponseError,
    validate_match_output,
)
from app.schemas.ai import AIMatchOutput


ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_MATCH_TOOL_NAME = "record_job_match"


class AnthropicAIProvider(AIProvider):
    name = "anthropic"

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
            raise AIProviderNotConfigured("Anthropic is not configured")
        response = await post_bounded_json(
            self.client,
            provider_name="Anthropic",
            url=ANTHROPIC_MESSAGES_URL,
            headers={
                "Accept": "application/json",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
            },
            payload={
                "model": self.model,
                "max_tokens": 4096,
                "system": request.system_prompt,
                "messages": [{"role": "user", "content": request.user_prompt}],
                "tools": [
                    {
                        "name": _MATCH_TOOL_NAME,
                        "description": (
                            "Record the complete structured job-to-profile match result. "
                            "Always supply every field from the schema exactly once."
                        ),
                        "input_schema": AIMatchOutput.model_json_schema(),
                    }
                ],
                "tool_choice": {"type": "tool", "name": _MATCH_TOOL_NAME},
            },
        )
        content = response.get("content")
        if isinstance(content, list):
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == _MATCH_TOOL_NAME
                ):
                    return validate_match_output(block.get("input"))
        raise AIProviderResponseError("Anthropic returned no structured match")
