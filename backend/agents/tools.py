from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.common.exceptions import ToolExecutionError
from backend.repositories.transactions import TransactionRepository
from backend.services.analytics import AnalyticsService
from backend.services.anomalies import AnomalyService
from backend.services.forecasting import ForecastService
from backend.services.multi_signal_anomalies import MultiSignalAnomalyService
from backend.services.recurrence import RecurrenceService
from backend.services.spending_explanation import SpendingExplanationService
from backend.services.categorization import CategorizationService
from backend.domain.transaction_eligibility import eligible_purchases


class MonthlySummaryArgs(BaseModel):
    """Arguments for monthly summary lookup."""

    model_config = ConfigDict(extra="forbid")

    as_of: date = Field(default_factory=date.today)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    account_id: UUID | None = None
    months: int = Field(default=12, ge=1, le=36)

    @model_validator(mode="after")
    def past_date(self):
        if self.as_of > date.today():
            raise ValueError("As-of date cannot be in the future")
        return self


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategorySpendingArgs(BaseModel):
    """Arguments for category spend lookup."""

    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    account_id: UUID | None = None

    @model_validator(mode="after")
    def valid_period(self):
        end = self.end_date or date.today()
        start = self.start_date or end - timedelta(days=89)
        if end > date.today() or start > end or (end - start).days > 365:
            raise ValueError("Choose a past date range of at most 366 days")
        return self


class LargestTransactionsArgs(BaseModel):
    """Arguments for largest transaction lookup."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=20)
    as_of: date = Field(default_factory=date.today)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    account_id: UUID | None = None

    @model_validator(mode="after")
    def past_date(self):
        if self.as_of > date.today():
            raise ValueError("As-of date cannot be in the future")
        return self


class SearchTransactionsArgs(BaseModel):
    """Arguments for transaction text search."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=20, ge=1, le=20)
    start_date: date | None = None
    end_date: date | None = None
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    account_id: UUID | None = None

    @model_validator(mode="after")
    def valid_period(self):
        end = self.end_date or date.today()
        start = self.start_date or end - timedelta(days=365)
        if end > date.today() or start > end or (end - start).days > 365:
            raise ValueError("Choose a past date range of at most 366 days")
        return self


class ScopedDates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    account_id: UUID | None = None

    @model_validator(mode="after")
    def valid_period(self):
        if self.end_date < self.start_date or self.end_date > date.today() \
                or (self.end_date - self.start_date).days > 365:
            raise ValueError("Choose a past date range of at most 366 days")
        return self


class ComparisonArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prior_start: date
    prior_end: date
    current_start: date
    current_end: date
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    account_id: UUID | None = None

    @model_validator(mode="after")
    def valid_periods(self):
        if self.prior_end < self.prior_start or self.current_end < self.current_start \
                or self.prior_end >= self.current_start or self.current_end > date.today() \
                or (self.prior_end - self.prior_start).days > 365 \
                or (self.current_end - self.current_start).days > 365:
            raise ValueError("Choose chronological, non-overlapping past periods of at most 366 days")
        return self


class AlertArgs(ScopedDates):
    limit: int = Field(default=5, ge=1, le=10)


class ForecastArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    account_id: UUID | None = None
    category_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,50}$")

    @model_validator(mode="after")
    def past_date(self):
        if self.as_of > date.today():
            raise ValueError("As-of date cannot be in the future")
        return self


class BudgetRiskArgs(ForecastArgs):
    category_id: str = Field(pattern=r"^[a-z0-9_]{1,50}$")


class RecurringArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    account_id: UUID | None = None
    limit: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def past_date(self):
        if self.as_of > date.today():
            raise ValueError("As-of date cannot be in the future")
        return self


class MerchantHistoryArgs(ScopedDates):
    merchant: str = Field(min_length=2, max_length=80)
    limit: int = Field(default=10, ge=1, le=20)


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
        self.session = session
        self.analytics = AnalyticsService(session)
        self.transactions = TransactionRepository(session)
        self.explanation = SpendingExplanationService(session)
        self.anomalies = MultiSignalAnomalyService(session)
        self.recurring = RecurrenceService(session)
        self.forecasting = ForecastService(session)
        self._tools = {
            "get_monthly_summary": AgentTool(
                name="get_monthly_summary",
                description="Summarize gross settled purchase debits and count by month in one currency and account scope.",
                args_schema=MonthlySummaryArgs,
                handler=self.get_monthly_summary,
            ),
            "get_spending_by_category": AgentTool(
                name="get_spending_by_category",
                description="Summarize gross settled purchase debits by category in one currency and optional date/account scope.",
                args_schema=CategorySpendingArgs,
                handler=self.get_spending_by_category,
            ),
            "get_largest_transactions": AgentTool(
                name="get_largest_transactions",
                description="Return the largest settled purchases in one currency and account scope.",
                args_schema=LargestTransactionsArgs,
                handler=self.get_largest_transactions,
            ),
            "search_transactions": AgentTool(
                name="search_transactions",
                description="Search settled purchases by merchant or fallback description in one currency and account scope.",
                args_schema=SearchTransactionsArgs,
                handler=self.search_transactions,
            ),
            "compare_spending_periods": AgentTool(
                name="compare_spending_periods",
                description="Compare two non-overlapping periods of gross settled purchases with category and merchant drivers.",
                args_schema=ComparisonArgs, handler=self.compare_spending_periods,
            ),
            "get_anomaly_summary": AgentTool(
                name="get_anomaly_summary",
                description="Explain amount, frequency, drift, and recurring-price alerts with evidence.",
                args_schema=AlertArgs, handler=self.get_anomaly_summary,
            ),
            "get_recurring_charge_summary": AgentTool(
                name="get_recurring_charge_summary",
                description="Summarize recurring payment candidates and review status in one currency.",
                args_schema=RecurringArgs, handler=self.get_recurring_charge_summary,
            ),
            "get_spending_forecast": AgentTool(
                name="get_spending_forecast",
                description="Get a bounded month-end gross-spending forecast and historical error range.",
                args_schema=ForecastArgs, handler=self.get_spending_forecast,
            ),
            "get_budget_risk": AgentTool(
                name="get_budget_risk",
                description="Compare a category forecast with its current monthly goal without claiming a probability.",
                args_schema=BudgetRiskArgs, handler=self.get_spending_forecast,
            ),
            "get_merchant_history": AgentTool(
                name="get_merchant_history",
                description="Show settled purchases at one merchant within account, currency, and date scope.",
                args_schema=MerchantHistoryArgs, handler=self.get_merchant_history,
            ),
            "get_categorization_summary": AgentTool(
                name="get_categorization_summary",
                description="Show category coverage and uncategorized count, without private model claims.",
                args_schema=NoArgs, handler=self.get_categorization_summary,
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
            if self.session.get_bind().dialect.name == "postgresql":
                self.session.execute(text("SET LOCAL statement_timeout = '5000ms'"))
            return tool.handler(**args.model_dump())
        except ValidationError as exc:
            raise ToolExecutionError(f"Invalid arguments for finance tool: {name}") from exc
        except Exception as exc:
            raise ToolExecutionError(f"Finance tool failed: {name}") from exc

    def _eligible_rows(self, start_date: date, end_date: date,
                       currency: str, account_id: UUID | None) -> list[dict]:
        rows = AnomalyService(self.session).purchase_rows(end_date, start_date,
                                                          str(account_id) if account_id else None)
        eligible, _ = eligible_purchases(rows, end_date)
        return [row for row in eligible if start_date <= row["posted_date"] <= end_date
                and row["currency"] == currency]

    def get_monthly_summary(self, as_of: date | None = None, currency: str = "USD",
                            account_id: UUID | None = None, months: int = 12) -> list[dict]:
        as_of = as_of or date.today()
        start_month = as_of.year * 12 + as_of.month - months + 1
        start = date((start_month - 1) // 12, (start_month - 1) % 12 + 1, 1)
        rows = self._eligible_rows(start, as_of, currency, account_id)
        totals = {}
        counts = {}
        for row in rows:
            month = row["posted_date"].strftime("%Y-%m")
            totals[month] = totals.get(month, Decimal(0)) + row["amount"]
            counts[month] = counts.get(month, 0) + 1
        return [{"month": month, "currency": currency, "gross_posted_purchases": str(totals[month]),
                 "transaction_count": counts[month]} for month in sorted(totals)[-months:]]

    def get_spending_by_category(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        currency: str = "USD",
        account_id: UUID | None = None,
    ) -> list[dict]:
        end = end_date or date.today()
        rows = self._eligible_rows(start_date or end - timedelta(days=89), end, currency, account_id)
        totals = {}
        counts = {}
        for row in rows:
            category = row["category_id"] or "uncategorized"
            totals[category] = totals.get(category, Decimal(0)) + row["amount"]
            counts[category] = counts.get(category, 0) + 1
        return [{"category_id": key, "currency": currency, "gross_posted_purchases": str(value),
                 "transaction_count": counts[key]} for key, value in
                sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:20]]

    def get_largest_transactions(self, limit: int = 10, as_of: date | None = None,
                                 currency: str = "USD", account_id: UUID | None = None) -> list[dict]:
        end = as_of or date.today()
        rows = self._eligible_rows(end - timedelta(days=365), end, currency, account_id)
        return [{"id": row["id"], "posted_date": row["posted_date"].isoformat(),
                 "merchant": row["merchant"], "amount": str(row["amount"]), "currency": currency}
                for row in sorted(rows, key=lambda item: (-item["amount"], item["posted_date"]))[:limit]]

    def search_transactions(self, query: str, limit: int = 20,
                            start_date: date | None = None, end_date: date | None = None,
                            currency: str = "USD", account_id: UUID | None = None) -> list[dict]:
        end = end_date or date.today()
        rows = self._eligible_rows(start_date or end - timedelta(days=365), end, currency, account_id)
        matched = [row for row in rows if query.casefold() in row["merchant"].casefold()
                   or query.casefold() in row.get("description", "").casefold()]
        return [{"id": row["id"], "posted_date": row["posted_date"].isoformat(),
                 "merchant": row["merchant"][:120], "amount": str(row["amount"]),
                 "currency": currency} for row in sorted(
                     matched, key=lambda item: (item["posted_date"], item["id"]), reverse=True)[:limit]]

    def compare_spending_periods(self, prior_start: date, prior_end: date,
                                 current_start: date, current_end: date,
                                 currency: str = "USD", account_id: UUID | None = None) -> dict:
        result = self.explanation.compare(prior_start, prior_end, current_start, current_end,
                                          currency, str(account_id) if account_id else None)
        def compact(items):
            return [{key: value[:10] if key.endswith("transaction_ids") else value
                     for key, value in item.items()} for item in items[:5]]
        return {**{key: result[key] for key in ("currency", "prior_period", "current_period",
                                                 "prior_total", "current_total", "delta",
                                                 "reconciliation_difference", "metric", "refund_policy")},
                "categories": compact(result["categories"]), "merchants": compact(result["merchants"])}

    def get_anomaly_summary(self, start_date: date, end_date: date, currency: str = "USD",
                            account_id: UUID | None = None, limit: int = 5) -> dict:
        result = self.anomalies.list_alerts(end_date, start_date, currency,
                                            str(account_id) if account_id else None)
        return {"alert_count": result["alert_count"], "currency": currency,
                "alerts": [{key: item.get(key) for key in ("alert_id", "signal_type", "entity_type",
                    "entity_id", "period_start", "period_end", "observed_value", "baseline_value",
                    "explanation", "review", "supporting_transaction_ids")}
                    for item in result["alerts"][:limit]],
                "limitations": result["limitations"]}

    def get_recurring_charge_summary(self, as_of: date, currency: str = "USD",
                                     account_id: UUID | None = None, limit: int = 5) -> dict:
        result = self.recurring.list_candidates(as_of, str(account_id) if account_id else None)
        candidates = [item for item in result["candidates"] if item["currency"] == currency]
        return {"candidate_count": len(candidates), "currency": currency,
                "candidates": [{key: item.get(key)[-10:] if key == "transaction_ids" else item.get(key) for key in ("series_key", "merchant", "cadence",
                    "review", "typical_amount", "latest_increase_vs_previous", "next_expected_date",
                    "transaction_ids", "reason")}
                    for item in candidates[:limit]]}

    def get_spending_forecast(self, as_of: date, currency: str = "USD",
                              account_id: UUID | None = None, category_id: str | None = None) -> dict:
        result = self.forecasting.forecast(as_of, currency, str(account_id) if account_id else None,
                                           category_id)
        return {key: result.get(key) for key in ("as_of", "month", "currency", "account_id",
                    "category_id", "method", "confidence", "observed_to_date", "forecast_total",
                    "lower_bound", "upper_bound", "budget", "budget_status", "forecast_overshoot",
                    "limitations")}

    def get_merchant_history(self, start_date: date, end_date: date, currency: str,
                             account_id: UUID | None, merchant: str, limit: int = 10) -> dict:
        rows = AnomalyService(self.session).purchase_rows(end_date, start_date,
                                                          str(account_id) if account_id else None)
        eligible, _ = eligible_purchases(rows, end_date)
        matching = [row for row in eligible if start_date <= row["posted_date"] <= end_date
                    and row["currency"] == currency and merchant.casefold() in row["merchant"].casefold()]
        matching = sorted(matching, key=lambda item: (item["posted_date"], item["id"]), reverse=True)
        return {"merchant_query": merchant, "currency": currency, "count": len(matching),
                "total": str(sum((item["amount"] for item in matching), Decimal(0))),
                "transactions": [{"id": item["id"], "posted_date": item["posted_date"].isoformat(),
                                  "amount": str(item["amount"]), "merchant": item["merchant"]}
                                 for item in matching[:limit]]}

    def get_categorization_summary(self) -> dict:
        return CategorizationService(self.session).summary()


def json_safe(value: Any) -> Any:
    """Convert service results into values safe to send to an LLM as JSON."""

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value
