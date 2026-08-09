from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    description: str = ""


class SearchProviderError(RuntimeError):
    pass


class SearchProviderNotConfigured(SearchProviderError):
    pass


class WebSearchProvider(ABC):
    name: str

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: str) -> list[WebSearchResult]:
        raise NotImplementedError


class DisabledSearchProvider(WebSearchProvider):
    name = "disabled"

    @property
    def is_configured(self) -> bool:
        return False

    async def search(self, query: str) -> list[WebSearchResult]:
        raise SearchProviderNotConfigured("Web discovery is disabled")
