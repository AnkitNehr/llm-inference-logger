from .base import Provider, StreamChunk
from .mock_provider import MockProvider
from .openai_provider import OpenAIProvider
from .anthropic_provider import AnthropicProvider
from .gemini_provider import GeminiProvider


def get_provider(name: str) -> Provider:
    name = (name or "").lower().strip()
    if name == "openai":
        return OpenAIProvider()
    if name == "anthropic":
        return AnthropicProvider()
    if name == "gemini":
        return GeminiProvider()
    if name == "mock":
        return MockProvider()
    raise ValueError(f"unknown provider: {name}")


__all__ = [
    "Provider",
    "StreamChunk",
    "MockProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "get_provider",
]
