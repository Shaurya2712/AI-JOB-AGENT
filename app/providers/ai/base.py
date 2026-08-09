from abc import ABC, abstractmethod
from dataclasses import dataclass
import json

from pydantic import ValidationError

from app.schemas.ai import AIMatchOutput


class AIProviderError(RuntimeError):
    pass


class AIProviderNotConfigured(AIProviderError):
    pass


class AIProviderResponseError(AIProviderError):
    pass


@dataclass(frozen=True)
class AIProviderRequest:
    system_prompt: str
    user_prompt: str


class AIProvider(ABC):
    name: str
    model: str

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def score_match(self, request: AIProviderRequest) -> AIMatchOutput:
        raise NotImplementedError


class DisabledAIProvider(AIProvider):
    name = "disabled"
    model = ""

    @property
    def is_configured(self) -> bool:
        return False

    async def score_match(self, request: AIProviderRequest) -> AIMatchOutput:
        raise AIProviderNotConfigured("AI matching is disabled")


def validate_match_output(value: object) -> AIMatchOutput:
    try:
        return AIMatchOutput.model_validate(value)
    except ValidationError as error:
        raise AIProviderResponseError(
            "AI provider returned an invalid structured match"
        ) from error


def parse_match_output_text(value: object) -> AIMatchOutput:
    if not isinstance(value, str) or not value.strip():
        raise AIProviderResponseError("AI provider returned no structured match")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise AIProviderResponseError(
            "AI provider returned malformed structured JSON"
        ) from error
    return validate_match_output(parsed)
