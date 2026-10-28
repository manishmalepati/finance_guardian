from evals.anomaly_benchmark import prior_features, synthetic_purchases


def test_benchmark_features_do_not_use_later_purchases():
    rows, _, cutoff = synthetic_purchases()
    initial = prior_features(rows)
    earlier_id = next(row["id"] for row in rows if row["posted_date"] < cutoff)
    later = [dict(row) for row in rows]
    for row in later:
        if row["posted_date"] >= cutoff:
            row["amount"] *= 100
    changed = prior_features(later)
    assert initial[earlier_id] == changed[earlier_id]
