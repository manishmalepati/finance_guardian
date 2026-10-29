"""Reproducible posted-date walk-forward comparison on synthetic monthly spending."""

import json
from datetime import date
from decimal import Decimal

from backend.services.forecasting import forecast_rows


def _row(identifier: str, day: date, amount: str, category: str) -> dict:
    return {"id": identifier, "account_id": "synthetic-account", "posted_date": day,
            "amount": Decimal(amount), "direction": "debit", "status": "active",
            "is_pending": False, "removed_at": None, "replaced_by_transaction_id": None,
            "currency": "USD", "source": "synthetic", "category_id": category,
            "merchant": "Synthetic Merchant", "normalized_merchant": "synthetic merchant"}


def synthetic_months() -> list[dict]:
    rows = []
    for month_index in range(18):
        year = 2025 + month_index // 12
        month = month_index % 12 + 1
        for day in (2, 10, 18, 26):
            rows.append(_row(f"groceries-{month_index}-{day}", date(year, month, day),
                             str(30 + month_index % 3), "groceries"))
        if month_index % 3 == 0:
            rows.append(_row(f"travel-{month_index}", date(year, month, 12),
                             str(150 + 20 * (month_index // 3)), "travel"))
    for day in (2, 10):
        rows.append(_row(f"groceries-current-{day}", date(2026, 7, day), "31", "groceries"))
    return rows


def evaluate() -> dict:
    rows = synthetic_months()
    as_of = date(2026, 7, 15)
    categories = {}
    for category in ("groceries", "travel"):
        result = forecast_rows(rows, as_of, category_id=category)
        categories[category] = {key: result[key] for key in (
            "method", "confidence", "observed_to_date", "forecast_total",
            "lower_bound", "upper_bound", "historical_complete_months", "backtest")}
    return {"dataset": "synthetic_monthly_spending_v1", "seed": "deterministic_no_randomness",
            "month_count": 18, "cutoff_days": [7, 15, 22], "categories": categories,
            "limitations": "Synthetic posted-date evaluation; true historical ingestion coverage and category versions are unavailable."}


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
