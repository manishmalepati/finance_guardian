from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://finance_guardian:finance_guardian@localhost:5432/finance_guardian"
    llm_provider: str = ""
    llm_model: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def agent_configuration_error(self) -> str | None:
        provider = self.llm_provider.strip().lower()
        if provider not in {"anthropic", "openai"}:
            return "Agent is not configured. Set LLM_PROVIDER to 'anthropic' or 'openai'."
        if not self.llm_model.strip():
            return "Agent is not configured. Set LLM_MODEL for the selected provider."
        if provider == "anthropic" and not self.anthropic_api_key.strip():
            return "Agent is not configured. Set ANTHROPIC_API_KEY before using chat."
        if provider == "openai" and not self.openai_api_key.strip():
            return "Agent is not configured. Set OPENAI_API_KEY before using chat."
        return None


settings = Settings()
