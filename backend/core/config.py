from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.common.exceptions import ConfigurationError


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str = "postgresql+psycopg://finance_guardian:finance_guardian@localhost:5432/finance_guardian"
    llm_provider: str = ""
    llm_model: str = ""
    anthropic_api_key: str = ""
    anthropic_workspace_id: str = ""
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"
    plaid_products: str = "transactions"
    plaid_country_codes: str = "US"
    plaid_client_name: str = "Finance Guardian"

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

    def plaid_configuration_error(self) -> str | None:
        """Return a user-safe error when Plaid cannot be used."""

        if not self.plaid_client_id.strip():
            return "Plaid is not configured. Set PLAID_CLIENT_ID."
        if not self.plaid_secret.strip():
            return "Plaid is not configured. Set PLAID_SECRET."
        if self.plaid_env.strip().lower() not in {"sandbox", "production"}:
            return "Plaid is not configured. Set PLAID_ENV to 'sandbox' or 'production'."
        return None

    def require_plaid_configuration(self) -> None:
        """Raise when Plaid credentials or environment are incomplete."""

        configuration_error = self.plaid_configuration_error()
        if configuration_error:
            raise ConfigurationError(configuration_error)

    @property
    def plaid_product_list(self) -> list[str]:
        return [product.strip() for product in self.plaid_products.split(",") if product.strip()]

    @property
    def plaid_country_code_list(self) -> list[str]:
        return [country.strip().upper() for country in self.plaid_country_codes.split(",") if country.strip()]


settings = Settings()
