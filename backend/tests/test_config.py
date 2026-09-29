import pytest

from backend.common.exceptions import ConfigurationError
from backend.core.config import Settings


def test_require_agent_configuration_raises_without_provider():
    settings = Settings(llm_provider="", llm_model="", anthropic_api_key="")

    with pytest.raises(ConfigurationError, match="LLM_PROVIDER"):
        settings.require_agent_configuration()
