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


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIProvider(AIProvider):
    name = "openai"

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
            raise AIProviderNotConfigured("OpenAI is not configured")
        response = await post_bounded_json(
            self.client,
            provider_name="OpenAI",
            url=OPENAI_RESPONSES_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload={
                "model": self.model,
                "instructions": request.system_prompt,
                "input": request.user_prompt,
                "store": False,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "job_match",
                        "strict": True,
                        "schema": AIMatchOutput.model_json_schema(),
                    }
                },
            },
        )
        output_text = response.get("output_text")
        if isinstance(output_text, str):
            return parse_match_output_text(output_text)
        output = response.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict) or not isinstance(item.get("content"), list):
                    continue
                for content in item["content"]:
                    if isinstance(content, dict) and content.get("type") == "output_text":
                        return parse_match_output_text(content.get("text"))
        raise AIProviderResponseError("OpenAI returned no structured match")
