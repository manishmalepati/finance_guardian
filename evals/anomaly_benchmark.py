"""Seeded synthetic comparison; never reads a database or stores private records."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from math import log1p
from statistics import median
from time import perf_counter

from backend.services.anomalies import score_purchases


def synthetic_purchases() -> tuple[list[dict], set[str], date]:
    start = date(2025, 1, 1)
    cutoff = start + timedelta(weeks=18)
    rows = []
    seeded = set()
    for week in range(26):
        for merchant in range(10):
            identifier = f"synthetic-{week:02d}-{merchant:02d}"
            base = Decimal(12 + merchant * 6)
            amount = base + Decimal((week * 3 + merchant) % 5 - 2)
            if week >= 18 and (week, merchant) in {
                (18, 1), (19, 4), (20, 7), (21, 2), (22, 8), (23, 5), (24, 0), (25, 9),
            }:
                amount *= 4
                seeded.add(identifier)
            rows.append({
                "id": identifier, "account_id": "synthetic-account",
                "posted_date": start + timedelta(weeks=week, days=merchant % 5),
                "amount": amount, "direction": "debit", "status": "active", "is_pending": False,
                "removed_at": None, "replaced_by_transaction_id": None, "currency": "USD",
                "source": "synthetic", "category_id": "synthetic-category",
                "merchant": f"Synthetic merchant {merchant}",
                "normalized_merchant": f"synthetic merchant {merchant}",
            })
    return rows, seeded, cutoff


def prior_features(rows: list[dict]) -> dict[str, list[float]]:
    """Every feature uses only dates strictly before the scored purchase."""
    history = defaultdict(list)
    features = {}
    for row in sorted(rows, key=lambda item: (item["posted_date"], item["id"])):
        earlier = [item for item in history[row["normalized_merchant"]]
                   if item["posted_date"] < row["posted_date"]]
        typical = float(median([item["amount"] for item in earlier])) if earlier else float(row["amount"])
        recent = sum((row["posted_date"] - item["posted_date"]).days <= 30 for item in earlier)
        features[row["id"]] = [log1p(float(row["amount"])),
                               log1p(float(row["amount"]) / max(typical, 1)),
                               float(recent)]
        history[row["normalized_merchant"]].append(row)
    return features


def evaluate() -> dict:
    from sklearn import __version__ as sklearn_version
    from sklearn.ensemble import IsolationForest

    rows, seeded, cutoff = synthetic_purchases()
    end = max(item["posted_date"] for item in rows)
    evaluation = [item for item in rows if item["posted_date"] >= cutoff]
    features = prior_features(rows)
    train = [features[item["id"]] for item in rows if item["posted_date"] < cutoff]
    test = [features[item["id"]] for item in evaluation]
    started = perf_counter()
    baseline = score_purchases(rows, end, cutoff, "USD")
    baseline_ms = (perf_counter() - started) * 1000
    started = perf_counter()
    forest = IsolationForest(n_estimators=100, contamination="auto", random_state=2718).fit(train)
    forest_scores = forest.decision_function(test)
    forest_ms = (perf_counter() - started) * 1000
    k = len(seeded)
    baseline_top = [item["transaction_id"] for item in baseline["alerts"][:k]]
    forest_top = [item["id"] for _, item in sorted(zip(forest_scores, evaluation),
                                                     key=lambda pair: pair[0])[:k]]

    def metrics(top: list[str], alert_count: int, elapsed_ms: float) -> dict:
        hits = len(set(top) & seeded)
        return {"precision_at_k": round(hits / k, 3), "seeded_recall_at_k": round(hits / k, 3),
                "alerts_per_100": round(alert_count * 100 / len(evaluation), 1),
                "latency_ms": round(elapsed_ms, 1)}

    return {"dataset": "seeded_synthetic_amount_spikes_v1", "seed": 2718,
            "scikit_learn_version": sklearn_version, "training_count": len(train),
            "evaluation_count": len(evaluation), "seeded_event_count": k,
            "precision_k": k,
            "baseline": metrics(baseline_top, len(baseline["alerts"]), baseline_ms),
            "isolation_forest": metrics(forest_top, k, forest_ms),
            "forest_alert_policy": "top_k_for_comparison_only",
            "real_reviewed_labels": 0,
            "deployment_decision": "baseline_only_until_real_reviewed_cases_exist"}


if __name__ == "__main__":
    import json
    print(json.dumps(evaluate(), indent=2))
