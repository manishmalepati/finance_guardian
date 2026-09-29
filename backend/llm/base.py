from typing import Protocol


class LLMProvider(Protocol):
    """Minimal contract the agent needs from an LLM provider."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Return the model's text response for a single-turn instruction."""
