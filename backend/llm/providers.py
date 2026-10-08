from __future__ import annotations

from backend.common.exceptions import ConfigurationError
from backend.core.config import Settings, settings
from backend.llm.base import LLMProvider


class AnthropicProvider:
    """Claude-backed provider used by the Finance Guardian agent."""

    def __init__(self, api_key: str, model: str, max_tokens: int = 300):
        from anthropic import Anthropic

        self.model = model
        self.max_tokens = max_tokens
        self.client = Anthropic(api_key=api_key)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")


class LLMProviderFactory:
    """Factory for production LLM providers.

    A Factory is enough for the MVP because provider construction is currently a
    single decision. A Builder/Director becomes useful once we add multiple
    construction steps such as retries, tracing, budget limits, and LangFuse.
    """

    def __init__(self, app_settings: Settings = settings):
        self.settings = app_settings

    def build(self, max_tokens: int = 300) -> LLMProvider:
        """Build the configured provider without falling back to a mock."""

        provider = self.settings.llm_provider.strip().lower()
        if provider != "anthropic":
            raise ConfigurationError("Unsupported LLM provider. Set LLM_PROVIDER to 'anthropic'.")
        return AnthropicProvider(
            api_key=self.settings.anthropic_api_key,
            model=self.settings.llm_model,
            max_tokens=max_tokens,
        )
