from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for expected application failures."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "app_error"
    user_message = "Something went wrong."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.user_message)
        self.message = message or self.user_message


class ConfigurationError(AppError):
    """Raised when required local configuration is missing or unsupported."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "configuration_error"
    user_message = "Application configuration is incomplete."


class AgentExecutionError(AppError):
    """Raised when the agent cannot complete a request safely."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "agent_execution_error"
    user_message = "Agent execution failed. Check LLM credentials, model configuration, and logs."


class AgentPlanningError(AgentExecutionError):
    """Raised when the LLM returns an invalid or unsafe tool plan."""

    error_code = "agent_planning_error"
    user_message = "Agent planning failed. Try rephrasing the question."


class ToolExecutionError(AgentExecutionError):
    """Raised when an approved tool cannot validate or execute."""

    error_code = "tool_execution_error"
    user_message = "The selected finance tool could not run."


class IngestionError(AppError):
    """Raised when a statement import cannot be completed."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "ingestion_error"
    user_message = "Statement import failed."


class UnsupportedSourceError(IngestionError):
    """Raised when no adapter exists for the requested source."""

    error_code = "unsupported_source"


class PlaidIntegrationError(AppError):
    """Raised when a Plaid request or sync cannot be completed."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "plaid_integration_error"
    user_message = "Plaid integration failed."


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Map expected application exceptions to stable API errors."""

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error_code, "detail": exc.message},
    )
