from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.common.exceptions import ConfigurationError


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str = "postgresql+psycopg://finance_guardian:finance_guardian@localhost:5432/finance_guardian"
    llm_provider: str = ""
    llm_model: str = ""
    anthropic_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def agent_configuration_error(self) -> str | None:
        """Return a user-safe error when chat cannot use a real LLM."""

        provider = self.llm_provider.strip().lower()
        if provider != "anthropic":
            return "Agent is not configured. Set LLM_PROVIDER to 'anthropic'."
        if not self.llm_model.strip():
            return "Agent is not configured. Set LLM_MODEL for the selected provider."
        if not self.anthropic_api_key.strip():
            return "Agent is not configured. Set ANTHROPIC_API_KEY before using chat."
        return None

    def require_agent_configuration(self) -> None:
        """Raise when the agent cannot use a configured production LLM."""

        configuration_error = self.agent_configuration_error()
        if configuration_error:
            raise ConfigurationError(configuration_error)


settings = Settings()
