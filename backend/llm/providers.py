from __future__ import annotations

from backend.common.exceptions import ConfigurationError
from backend.core.config import Settings, settings
from backend.llm.base import LLMProvider


class AnthropicProvider:
    """Claude-backed provider used by the Finance Guardian agent."""

    def __init__(self, api_key: str, model: str, max_tokens: int = 300, workspace_id: str = ""):
        from anthropic import Anthropic

        self.model = model
        self.max_tokens = max_tokens
        default_headers = {}
        if workspace_id.strip():
            default_headers["anthropic-workspace-id"] = workspace_id.strip()
        self.client = Anthropic(api_key=api_key, default_headers=default_headers or None, timeout=20.0)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")


class OllamaProvider:
    """Explicitly configured local or privately hosted Ollama endpoint."""

    def __init__(self, base_url: str, model: str, max_tokens: int = 300):
        import httpx

        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=20.0)
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.post("/api/generate", json={
            "model": self.model, "system": system_prompt, "prompt": user_prompt,
            "stream": False, "options": {"temperature": 0, "num_predict": self.max_tokens},
        })
        response.raise_for_status()
        return str(response.json()["response"])


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
        self.settings.require_agent_configuration()
        if provider == "ollama":
            return OllamaProvider(
                base_url=self.settings.ollama_base_url,
                model=self.settings.llm_model,
                max_tokens=max_tokens,
            )
        if provider != "anthropic":
            raise ConfigurationError("Unsupported LLM provider.")
        return AnthropicProvider(
            api_key=self.settings.anthropic_api_key,
            model=self.settings.llm_model,
            max_tokens=max_tokens,
            workspace_id=self.settings.anthropic_workspace_id,
        )
