from datetime import date, timedelta
from decimal import Decimal

from backend.services.anomalies import eligible_purchases, score_purchases


DAY = date(2026, 10, 1)


def event(identifier, offset, amount="10.00", **changes):
    row = {"id": identifier, "account_id": "account-1", "posted_date": DAY + timedelta(days=offset),
           "amount": Decimal(amount), "direction": "debit", "status": "active", "is_pending": False,
           "removed_at": None, "replaced_by_transaction_id": None, "currency": "USD", "source": "plaid",
           "category_id": "food_dining", "merchant": "Synthetic Cafe", "normalized_merchant": "synthetic cafe"}
    row.update(changes)
    return row


def test_prior_only_reference_and_evidence():
    rows = [event(str(index), index, "10.00") for index in range(5)]
    rows += [event("spike", 5, "80.00"), event("future", 6, "100.00")]
    result = score_purchases(rows, DAY + timedelta(days=5), DAY + timedelta(days=5), "USD")
    assert result["alert_count"] == 1
    alert = result["alerts"][0]
    assert alert["transaction_id"] == "spike"
    assert alert["reference_kind"] == "merchant"
    assert alert["reference_count"] == 5
    assert alert["reference_transaction_ids"] == [str(index) for index in range(5)]
    assert result["excluded_counts"]["not_settled_active"] == 1
    assert result["probability_claim"] is False


def test_same_day_charges_are_not_each_others_reference():
    rows = [event(str(index), index, "10.00") for index in range(4)]
    rows += [event("same-day-normal", 4, "10.00"), event("same-day-spike", 4, "80.00")]
    assert score_purchases(rows, DAY + timedelta(days=4), DAY + timedelta(days=4), "USD")["alerts"] == []


def test_pending_refunds_transfers_currency_and_exact_overlap():
    rows = [event(str(index), index) for index in range(5)]
    rows += [event("pending", 5, "100", is_pending=True),
             event("refund", 5, "100", direction="credit"),
             event("transfer", 5, "100", category_id="financial_transfers"),
             event("eur", 5, "100", currency="EUR"),
             event("statement-copy", 4, source="statement"),
             event("alert", 5, "100")]
    result = score_purchases(rows, DAY + timedelta(days=5), DAY, "USD")
    assert [item["transaction_id"] for item in result["alerts"]] == ["alert"]
    assert result["excluded_counts"]["not_settled_active"] == 1
    assert result["excluded_counts"]["credits_including_refunds"] == 1
    assert result["excluded_counts"]["transfers_and_card_payments"] == 1
    assert result["excluded_counts"]["exact_statement_plaid_overlap"] == 1


def test_accounts_do_not_share_reference_history():
    rows = [event(str(index), index) for index in range(5)]
    rows.append(event("other-account", 5, "100", account_id="account-2"))
    assert score_purchases(rows, DAY + timedelta(days=5), DAY, "USD")["alerts"] == []


def test_duplicate_statement_count_preserves_extra_real_purchase():
    rows = [event("plaid", 0), event("copy", 0, source="statement"),
            event("extra", 0, source="statement")]
    purchases, excluded = eligible_purchases(rows, DAY)
    assert {item["id"] for item in purchases} == {"plaid", "extra"}
    assert excluded["exact_statement_plaid_overlap"] == 1


def test_uniform_history_has_finite_score_and_small_change_is_not_flagged():
    rows = [event(str(index), index) for index in range(5)]
    rows += [event("small-change", 5, "12.00"), event("large-change", 6, "50.00")]
    result = score_purchases(rows, DAY + timedelta(days=6), DAY, "USD")
    assert [item["transaction_id"] for item in result["alerts"]] == ["large-change"]
    assert result["alerts"][0]["score"] < 100


def test_category_fallback_needs_prior_observations_and_keeps_currency_separate():
    rows = [event(f"prior-{index}", index, merchant=f"Synthetic {index}",
                  normalized_merchant=f"synthetic {index}") for index in range(12)]
    rows += [event("eur", 12, "200.00", currency="EUR", merchant="Euro merchant",
                   normalized_merchant="euro merchant"),
             event("usd", 12, "100.00", merchant="New merchant",
                   normalized_merchant="new merchant")]
    result = score_purchases(rows, DAY + timedelta(days=12), DAY + timedelta(days=12), "USD")
    assert len(result["alerts"]) == 1
    assert result["alerts"][0]["reference_kind"] == "category"
    assert result["alerts"][0]["reference_count"] == 12
