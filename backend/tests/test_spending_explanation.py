from datetime import date
from decimal import Decimal

from backend.services.spending_explanation import explain_rows


PRIOR_START = date(2026, 8, 1)
PRIOR_END = date(2026, 8, 31)
CURRENT_START = date(2026, 9, 1)
CURRENT_END = date(2026, 9, 30)


def row(identifier, day, amount, merchant="Market", category="food", **changes):
    value = {
        "id": identifier, "account_id": "account-one", "posted_date": day,
        "amount": Decimal(amount), "direction": "debit", "status": "active",
        "is_pending": False, "removed_at": None, "replaced_by_transaction_id": None,
        "currency": "USD", "source": "plaid", "category_id": category,
        "category_name": category.title(), "movement_category_id": "food_groceries",
        "merchant": merchant,
    }
    value.update(changes)
    return value


def compare(rows):
    return explain_rows(rows, prior_start=PRIOR_START, prior_end=PRIOR_END,
                        current_start=CURRENT_START, current_end=CURRENT_END,
                        currency="USD")


def test_frequency_and_ticket_effects_reconcile_with_positive_and_negative_drivers():
    result = compare([
        row("p1", date(2026, 8, 4), "10.00"),
        row("p2", date(2026, 8, 8), "20.00"),
        row("c1", date(2026, 9, 4), "20.00"),
        row("c2", date(2026, 9, 8), "20.00"),
        row("c3", date(2026, 9, 9), "20.00"),
        row("p3", date(2026, 8, 10), "15.00", "Cinema", "fun"),
        row("c4", date(2026, 9, 10), "5.00", "Cinema", "fun"),
    ])
    assert result["prior_total"] == "45.00"
    assert result["current_total"] == "65.00"
    assert result["delta"] == "20.00"
    assert result["reconciliation_difference"] == "0.00"
    market = next(item for item in result["merchants"] if item["name"] == "Market")
    assert market["frequency_effect"] == "15.00"
    assert market["average_amount_effect"] == "15.00"
    assert market["current_transaction_ids"] == ["c1", "c2", "c3"]
    assert sum(Decimal(item["delta"]) for item in result["categories"]) == Decimal("20.00")
    assert sum(Decimal(item["delta"]) for item in result["merchants"]) == Decimal("20.00")


def test_empty_baseline_new_and_vanished_merchants_and_category_change():
    result = compare([
        row("old", date(2026, 8, 1), "8.00", "Old", "food"),
        row("recat-prior", date(2026, 8, 3), "7.00", "Same", "food"),
        row("new", date(2026, 9, 2), "12.00", "New", "fun"),
        row("recat-current", date(2026, 9, 3), "7.00", "Same", "fun"),
    ])
    assert result["delta"] == "4.00"
    assert {item["change_kind"] for item in result["merchants"]} == {"new", "vanished"}
    assert all(item["average_amount_effect"] == "0.00" for item in result["merchants"])
    assert result["reconciliation_difference"] == "0.00"


def test_excludes_pending_superseded_removed_transfers_credits_and_other_currency():
    result = compare([
        row("valid", date(2026, 9, 2), "10.00"),
        row("pending", date(2026, 9, 2), "99.00", is_pending=True),
        row("superseded", date(2026, 9, 2), "99.00", status="superseded"),
        row("removed", date(2026, 9, 2), "99.00", removed_at=date(2026, 9, 3)),
        row("transfer", date(2026, 9, 2), "99.00", movement_category_id="financial_transfers"),
        row("card", date(2026, 9, 2), "99.00", movement_category_id="financial_credit_card_payment"),
        row("refund", date(2026, 9, 2), "99.00", direction="credit", movement_category_id="income_refunds_reimbursements"),
        row("eur", date(2026, 9, 2), "99.00", currency="EUR"),
    ])
    assert result["current_total"] == "10.00"
    assert result["excluded_counts"] == {
        "not_posted_active": 3, "other_or_missing_currency": 1,
        "credits_including_refunds": 1, "transfers_and_card_payments": 2,
    }


def test_exact_statement_plaid_overlap_pairs_by_occurrence_without_dropping_extra_purchase():
    rows = [
        row("plaid-1", date(2026, 9, 2), "10.00", "Cafe"),
        row("statement-1", date(2026, 9, 2), "10.00", "Cafe", source="statement"),
        row("statement-2", date(2026, 9, 2), "10.00", "Cafe", source="statement"),
        row("statement-other-account", date(2026, 9, 2), "10.00", "Cafe", source="statement", account_id="account-two"),
    ]
    result = compare(rows)
    assert result["current_total"] == "30.00"
    assert result["excluded_counts"]["exact_statement_plaid_overlap"] == 1
    assert len(result["merchants"][0]["current_transaction_ids"]) == 3


def test_fractional_average_allocates_exact_cents_and_empty_periods_work():
    result = compare([
        row("p1", date(2026, 8, 1), "0.01"),
        row("p2", date(2026, 8, 2), "0.01"),
        row("p3", date(2026, 8, 3), "0.02"),
        row("c1", date(2026, 9, 1), "0.02"),
    ])
    merchant = result["merchants"][0]
    assert Decimal(merchant["frequency_effect"]) + Decimal(merchant["average_amount_effect"]) == Decimal(merchant["delta"])
    assert result["reconciliation_difference"] == "0.00"
    assert compare([])["categories"] == []
    assert compare([])["delta"] == "0.00"


def test_pending_to_posted_transition_and_repeated_canonical_id_count_once():
    posted = row("posted", date(2026, 9, 4), "23.40")
    result = compare([
        row("pending", date(2026, 9, 3), "23.40", status="removed",
            is_pending=True, replaced_by_transaction_id="posted"),
        posted,
        dict(posted),  # A bad join must not multiply the canonical transaction.
    ])
    assert result["current_total"] == "23.40"
    assert result["current_count"] == 1
    assert result["excluded_counts"]["duplicate_canonical_id"] == 1
    assert result["reconciliation_difference"] == "0.00"
