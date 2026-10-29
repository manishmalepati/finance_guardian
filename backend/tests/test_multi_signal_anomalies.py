from datetime import date, timedelta
from decimal import Decimal

from backend.services.multi_signal_anomalies import detect_signals


MONDAY = date(2026, 1, 5)


def event(identifier: str, day: date, amount: str = "10.00", **changes) -> dict:
    row = {"id": identifier, "account_id": "account-1", "posted_date": day,
           "amount": Decimal(amount), "direction": "debit", "status": "active",
           "is_pending": False, "removed_at": None, "replaced_by_transaction_id": None,
           "currency": "USD", "source": "plaid", "category_id": "food_dining",
           "merchant": "Synthetic Cafe", "normalized_merchant": "synthetic cafe"}
    row.update(changes)
    return row


def test_completed_week_frequency_burst_and_sparse_history():
    rows = [event(f"normal-{week}-{n}", MONDAY + timedelta(weeks=week, days=n),
                  merchant="Synthetic Cafe", normalized_merchant="synthetic cafe")
            for week in range(8) for n in range(2)]
    rows += [event(f"burst-{n}", MONDAY + timedelta(weeks=8, days=n % 7)) for n in range(8)]
    rows += [event("new-merchant", MONDAY + timedelta(weeks=8), merchant="New Place",
                   normalized_merchant="new place")]
    result = detect_signals(rows, MONDAY + timedelta(weeks=9), MONDAY + timedelta(weeks=8), "USD")
    merchant = [item for item in result["alerts"] if item["signal_type"] == "frequency"
                and item["entity_type"] == "merchant"]
    assert len(merchant) == 1
    assert merchant[0]["observed_value"] == "8"
    assert merchant[0]["baseline_value"] == "2"
    assert len(merchant[0]["supporting_transaction_ids"]) == 8
    # A newly observed merchant has no credible weekly baseline.
    assert all(item["entity_id"] != "new place" for item in result["alerts"])
    partial = detect_signals(rows, MONDAY + timedelta(weeks=8, days=3),
                             MONDAY + timedelta(weeks=8), "USD")
    assert not any(item["signal_type"] == "frequency" for item in partial["alerts"])


def test_sustained_drift_requires_three_completed_weeks():
    rows = [event(f"week-{week}", MONDAY + timedelta(weeks=week),
                  "25.00" if week >= 9 else "10.00") for week in range(12)]
    result = detect_signals(rows, MONDAY + timedelta(weeks=12), MONDAY, "USD")
    drift = [item for item in result["alerts"] if item["signal_type"] == "drift"]
    assert len(drift) == 1
    assert drift[0]["baseline_value"] == "10.00"
    assert drift[0]["observed_value"] == "25.00"
    assert drift[0]["sustained_weeks"] == 3
    early = detect_signals(rows, MONDAY + timedelta(weeks=11), MONDAY, "USD")
    assert not any(item["signal_type"] == "drift" for item in early["alerts"])


def test_recurring_price_change_and_account_currency_isolation():
    dates = [date(2026, month, 1) for month in (1, 2, 3, 4)]
    rows = [event(f"bill-{i}", day, "12.00" if i == 3 else "10.00",
                  merchant="Synthetic Utility", normalized_merchant="synthetic utility")
            for i, day in enumerate(dates)]
    rows += [event("other-account", dates[-1], "500.00", account_id="account-2")]
    rows += [event("other-currency", dates[-1], "500.00", currency="EUR")]
    rows += [event("pending-copy", dates[-1], "12.00", is_pending=True)]
    result = detect_signals(rows, date(2026, 4, 2), date(2026, 4, 1), "USD", "account-1")
    prices = [item for item in result["alerts"] if item["signal_type"] == "recurring_price"]
    assert len(prices) == 1
    assert prices[0]["observed_value"] == "12.00"
    assert prices[0]["baseline_value"] == "10.00"
    assert prices[0]["account_id"] == "account-1"
    assert result["eligible_purchase_count"] == 4
    assert result["excluded_counts"]["not_settled_active"] == 1
