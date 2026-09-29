from __future__ import annotations

from backend.core.config import Settings, settings
from backend.llm.base import LLMProvider


class AnthropicProvider:
    """Claude-backed provider used by the Finance Guardian agent."""

    def __init__(self, api_key: str, model: str):
        from anthropic import Anthropic

        self.model = model
        self.client = Anthropic(api_key=api_key)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1200,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")


def build_llm_provider(app_settings: Settings = settings) -> LLMProvider:
    """Build the configured production LLM provider.

    The API route validates configuration before constructing the provider, so
    this function intentionally does not fall back to a mock or static planner.
    """

    provider = app_settings.llm_provider.strip().lower()
    if provider != "anthropic":
        raise ValueError("Unsupported LLM provider")
    return AnthropicProvider(
        api_key=app_settings.anthropic_api_key,
        model=app_settings.llm_model,
    )
