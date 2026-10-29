from datetime import date
from decimal import Decimal

from backend.services.forecasting import backtest_rows, forecast_rows


def row(identifier: str, day: date, amount: str = "50.00", **changes) -> dict:
    result = {"id": identifier, "account_id": "account-1", "posted_date": day,
              "amount": Decimal(amount), "direction": "debit", "status": "active",
              "is_pending": False, "removed_at": None, "replaced_by_transaction_id": None,
              "currency": "USD", "source": "plaid", "category_id": "groceries",
              "merchant": "Synthetic Market", "normalized_merchant": "synthetic market"}
    result.update(changes)
    return result


def test_stable_monthly_history_selects_evaluated_baseline_and_budget_status():
    rows = [row(f"{month}-early", date(2026, month, 5)) for month in range(1, 8)]
    rows += [row(f"{month}-late", date(2026, month, 20)) for month in range(1, 7)]
    result = forecast_rows(rows, date(2026, 7, 15), category_id="groceries",
                           budget=Decimal("90.00"))
    assert result["observed_to_date"] == "50.00"
    assert result["historical_complete_months"] == 6
    assert result["method"] == "historical_monthly_median"
    assert result["forecast_total"] == "100.00"
    assert result["budget_status"] == "projected_over_budget"
    assert result["forecast_overshoot"] == "10.00"
    assert result["lower_bound"] is not None
    assert result["backtest"]["metrics"]["historical_monthly_median"]["cases"] >= 6


def test_sparse_history_is_provisional_and_future_purchase_is_not_seen():
    rows = [row("past", date(2026, 5, 5), "20.00"),
            row("current", date(2026, 6, 5), "30.00"),
            row("future", date(2026, 6, 20), "999.00")]
    result = forecast_rows(rows, date(2026, 6, 10))
    assert result["method"] == "daily_run_rate"
    assert result["confidence"] == "provisional"
    assert result["observed_to_date"] == "30.00"
    assert result["lower_bound"] is None


def test_currency_account_category_and_pending_are_isolated():
    rows = [row("usd", date(2026, 6, 5), "10.00"),
            row("eur", date(2026, 6, 5), "100.00", currency="EUR"),
            row("other-account", date(2026, 6, 5), "100.00", account_id="account-2"),
            row("other-category", date(2026, 6, 5), "100.00", category_id="travel"),
            row("pending", date(2026, 6, 5), "100.00", is_pending=True),
            row("credit", date(2026, 6, 5), "100.00", direction="credit")]
    result = forecast_rows(rows, date(2026, 6, 10), account_id="account-1",
                           category_id="groceries")
    assert result["observed_to_date"] == "10.00"
    assert result["eligible_purchase_count"] == 1
    assert result["excluded_counts"]["not_settled_active"] == 1
    assert result["excluded_counts"]["credits_including_refunds"] == 1


def test_zero_history_abstains_and_backtest_is_chronological():
    result = forecast_rows([], date(2026, 6, 10), budget=Decimal("100"))
    assert result["forecast_total"] is None
    assert result["budget_status"] == "insufficient_data"
    rows = [row("jan", date(2026, 1, 1)), row("feb", date(2026, 2, 1)),
            row("mar", date(2026, 3, 1))]
    backtest = backtest_rows(rows, date(2026, 4, 1))
    assert backtest["metrics"]["daily_run_rate"]["cases"] == 9


def test_sporadic_category_without_current_activity_abstains():
    rows = [row("jan", date(2026, 1, 12), category_id="travel"),
            row("apr", date(2026, 4, 12), category_id="travel")]
    result = forecast_rows(rows, date(2026, 7, 15), category_id="travel")
    assert result["confidence"] == "insufficient_data"
    assert result["forecast_total"] is None
    assert result["historical_complete_months"] == 6
