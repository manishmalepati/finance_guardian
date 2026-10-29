"""Fixed synthetic scenario benchmark; labels describe scenarios, not detector thresholds."""

import json
from datetime import date, timedelta
from decimal import Decimal
from time import perf_counter

from backend.services.multi_signal_anomalies import detect_signals


START = date(2026, 1, 5)


def _event(identifier: str, account: str, day: date, amount: str, merchant: str,
           category: str) -> dict:
    return {"id": identifier, "account_id": account, "posted_date": day,
            "amount": Decimal(amount), "direction": "debit", "status": "active",
            "is_pending": False, "removed_at": None, "replaced_by_transaction_id": None,
            "currency": "USD", "source": "synthetic", "category_id": category,
            "merchant": merchant, "normalized_merchant": merchant.casefold()}


def synthetic_scenarios() -> tuple[list[dict], set[tuple[str, str, str]], date, date]:
    rows = []
    for week in range(13):
        rows.append(_event(f"amount-{week}", "amount-account", START + timedelta(weeks=week),
                           "120.00" if week == 12 else "20.00", "Synthetic Fuel", "fuel"))
        for n in range(7 if week == 12 else 2):
            rows.append(_event(f"freq-{week}-{n}", "frequency-account",
                               START + timedelta(weeks=week, days=n % 7), "9.00",
                               "Synthetic Cafe", "dining"))
    for week in range(12):
        for n in range(3 if week >= 9 else 2):
            rows.append(_event(f"drift-{week}-{n}", "drift-account",
                               START + timedelta(weeks=week, days=n), "40.00",
                               "Synthetic Market", "groceries"))
    for month, amount in ((1, "10.00"), (2, "10.00"), (3, "10.00"), (4, "12.00")):
        rows.append(_event(f"recurring-{month}", "recurring-account",
                           date(2026, month, 1), amount, "Synthetic Utility", "utilities"))
    rows.append(_event("normal-large", "rare-account", START + timedelta(weeks=12),
                       "500.00", "Synthetic Furniture", "home"))
    rows.append({**_event("pending-duplicate", "amount-account", START + timedelta(weeks=12),
                          "120.00", "Synthetic Fuel", "fuel"), "is_pending": True})
    labels = {
        ("amount", "amount-12", (START + timedelta(weeks=12)).isoformat()),
        ("frequency", "synthetic cafe", (START + timedelta(weeks=12)).isoformat()),
        ("drift", "groceries", (START + timedelta(weeks=9)).isoformat()),
        ("recurring_price", "synthetic utility", date(2026, 4, 1).isoformat()),
    }
    return rows, labels, START + timedelta(weeks=9), date(2026, 4, 6)


def evaluate() -> dict:
    rows, labels, start_date, as_of = synthetic_scenarios()
    started = perf_counter()
    result = detect_signals(rows, as_of, start_date, "USD")
    elapsed_ms = round((perf_counter() - started) * 1000, 2)
    predicted = {(alert["signal_type"],
                  "synthetic utility" if alert["signal_type"] == "recurring_price" else alert["entity_id"],
                  alert["period_start"]) for alert in result["alerts"]}
    hits = predicted & labels
    precision = len(hits) / len(predicted) if predicted else 0.0
    recall = len(hits) / len(labels)
    k = len(labels)
    top = result["alerts"][:k]
    top_keys = {(alert["signal_type"],
                 "synthetic utility" if alert["signal_type"] == "recurring_price" else alert["entity_id"],
                 alert["period_start"]) for alert in top}
    return {"dataset": "synthetic_behavioral_scenarios_v1", "seed": "deterministic_no_randomness",
            "observation_count": result["eligible_purchase_count"], "ground_truth_count": len(labels),
            "predicted_count": len(predicted), "true_positive_count": len(hits),
            "precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0,
            "precision_at_k": round(len(top_keys & labels) / k, 3), "k": k,
            "false_alerts_per_100_eligible_purchases": round((len(predicted) - len(hits)) * 100 / result["eligible_purchase_count"], 2),
            "runtime_ms": elapsed_ms,
            "false_positives": sorted([list(item) for item in predicted - labels]),
            "misses": sorted([list(item) for item in labels - predicted]),
            "limitations": "Synthetic scenarios are not real-world accuracy. Historical rows use current category state."}


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
