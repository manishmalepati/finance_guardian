from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from backend.common.exceptions import ToolExecutionError
from backend.repositories.transactions import TransactionRepository
from backend.services.analytics import AnalyticsService


class MonthlySummaryArgs(BaseModel):
    """Arguments for monthly summary lookup."""

    model_config = ConfigDict(extra="forbid")


class CategorySpendingArgs(BaseModel):
    """Arguments for category spend lookup."""

    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None


class LargestTransactionsArgs(BaseModel):
    """Arguments for largest transaction lookup."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=50)


class SearchTransactionsArgs(BaseModel):
    """Arguments for transaction text search."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=20, ge=1, le=100)


@dataclass(frozen=True)
class AgentTool:
    """A tool the LLM may request, plus its validation schema."""

    name: str
    description: str
    args_schema: type[BaseModel]
    handler: Any

    def schema_for_prompt(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "args_schema": self.args_schema.model_json_schema(),
        }


class FinanceTools:
    """Approved finance tools exposed to the agent graph.

    The LLM never receives a database connection. It chooses one of these tools,
    arguments are validated with Pydantic, and services/repositories do the work.
    """

    def __init__(self, session: Session):
        self.analytics = AnalyticsService(session)
        self.transactions = TransactionRepository(session)
        self._tools = {
            "get_monthly_summary": AgentTool(
                name="get_monthly_summary",
                description="Summarize debits, credits, net spend, and transaction count by month.",
                args_schema=MonthlySummaryArgs,
                handler=self.get_monthly_summary,
            ),
            "get_spending_by_category": AgentTool(
                name="get_spending_by_category",
                description="Summarize debit spending by category, optionally within a date range.",
                args_schema=CategorySpendingArgs,
                handler=self.get_spending_by_category,
            ),
            "get_largest_transactions": AgentTool(
                name="get_largest_transactions",
                description="Return the largest transactions by amount.",
                args_schema=LargestTransactionsArgs,
                handler=self.get_largest_transactions,
            ),
            "search_transactions": AgentTool(
                name="search_transactions",
                description="Search transactions by merchant or description text.",
                args_schema=SearchTransactionsArgs,
                handler=self.search_transactions,
            ),
        }

    def prompt_schema(self) -> list[dict[str, Any]]:
        """Return LLM-readable tool descriptions and JSON schemas."""

        return [tool.schema_for_prompt() for tool in self._tools.values()]

    def execute(self, name: str, raw_args: dict[str, Any]) -> Any:
        """Validate arguments and execute an approved tool."""

        tool = self._tools.get(name)
        if tool is None:
            raise ToolExecutionError(f"Unknown finance tool requested: {name}")
        try:
            args = tool.args_schema.model_validate(raw_args)
            return tool.handler(**args.model_dump())
        except ValidationError as exc:
            raise ToolExecutionError(f"Invalid arguments for finance tool: {name}") from exc
        except Exception as exc:
            raise ToolExecutionError(f"Finance tool failed: {name}") from exc

    def get_monthly_summary(self) -> list[dict]:
        return self.analytics.monthly_summary()

    def get_spending_by_category(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict]:
        return self.analytics.category_spending(start_date=start_date, end_date=end_date)

    def get_largest_transactions(self, limit: int = 10) -> list[dict]:
        return self.analytics.largest_transactions(limit=limit)

    def search_transactions(self, query: str, limit: int = 20) -> list[dict]:
        rows = self.transactions.list_transactions(query=query, limit=limit)
        return [
            {
                "id": row.id,
                "posted_date": row.posted_date.isoformat(),
                "description": row.description,
                "amount": row.amount,
                "direction": row.direction,
            }
            for row in rows
        ]


def json_safe(value: Any) -> Any:
    """Convert service results into values safe to send to an LLM as JSON."""

    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value
