"""Provider adapters behind one interface, plus the factory that picks one from settings."""

from app.providers.base import Extractor, ProviderError, SourceFile
from app.settings import Settings


def build_provider(settings: Settings, name: str | None = None) -> Extractor:
    """Create the adapter for `name` (default: the active provider). SDKs import lazily."""
    name = name or settings.provider
    if name == "anthropic":
        import anthropic

        from app.providers.anthropic import AnthropicProvider

        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or None,
            timeout=settings.provider_timeout_seconds,
            max_retries=1,
        )
        return AnthropicProvider(
            client,
            model=settings.anthropic_model,
            effort=settings.anthropic_effort,
            max_tokens=settings.anthropic_max_tokens,
        )
    if name == "openai":
        import openai

        from app.providers.openai import OpenAIProvider

        client = openai.AsyncOpenAI(
            api_key=settings.openai_api_key or None,
            timeout=settings.provider_timeout_seconds,
            max_retries=1,
        )
        return OpenAIProvider(client, model=settings.openai_model)

    from app.providers.mock import MockProvider

    return MockProvider(delay_seconds=settings.mock_delay_seconds)


__all__ = ["Extractor", "ProviderError", "SourceFile", "build_provider"]
