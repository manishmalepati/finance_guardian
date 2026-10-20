from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.api.routes.goals import GoalCreate, GoalUpdate
from backend.goals.evaluation import EvidenceRow, MonthlySpendMetric, month_bounds


def goal(scope_kind="category", category_id="food_dining"):
    return SimpleNamespace(
        id="synthetic-goal", category_id=category_id, scope_kind=scope_kind,
        timezone="America/Los_Angeles", currency="USD", threshold_amount=Decimal("100.00"),
    )


def evidence(day, amount, category_id, *, parent="food_dining", direction="debit",
             pending=False, currency="USD", status="active"):
    tx = SimpleNamespace(
        id=f"synthetic-{day}-{amount}-{category_id}-{direction}-{pending}-{currency}",
        posted_date=date(2026, 10, day), amount=Decimal(amount),
        direction=direction, is_pending=pending, status=status,
        iso_currency_code=currency, merchant_name="Synthetic shop", description="Synthetic shop",
    )
    return EvidenceRow(tx, category_id, parent)


def test_monthly_goal_counts_category_and_subcategory_with_evidence():
    rows = [
        evidence(1, "40.00", "food_groceries"),
        evidence(31, "30.00", "food_prepared"),
        evidence(31, "10.00", "food_groceries", direction="credit"),
        evidence(31, "20.00", "food_groceries", pending=True),
        evidence(31, "50.00", "food_groceries", currency=None),
        evidence(31, "50.00", "food_groceries", currency="EUR"),
        evidence(31, "50.00", "shopping_general", parent="shopping"),
        evidence(30, "100.00", "food_groceries"),
    ]
    rows[-1].transaction.posted_date = date(2026, 9, 30)
    parent = MonthlySpendMetric().evaluate(goal(), rows, "2026-10")
    child = MonthlySpendMetric().evaluate(goal("subcategory", "food_groceries"), rows, "2026-10")

    assert (parent["posted_gross"], parent["posted_credits"], parent["posted_spend"]) == (
        Decimal("70.00"), Decimal("10.00"), Decimal("60.00"),
    )
    assert parent["pending_net"] == Decimal("20.00")
    assert parent["projected_spend"] == Decimal("80.00")
    assert parent["progress_percent"] == Decimal("60.0")
    assert parent["period_end"] == "2026-10-31"
    assert len(parent["evidence"]) == 4
    assert parent["exclusions"] == {"unknown_currency": 1, "other_currency": 1}
    assert child["posted_spend"] == Decimal("30.00")
    assert len(child["evidence"]) == 3


def test_month_boundary_uses_goal_timezone_and_overage_is_explicit():
    instant = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert month_bounds(None, "America/Los_Angeles", instant) == (date(2026, 10, 1), date(2026, 10, 31))
    assert month_bounds(None, "UTC", instant) == (date(2026, 11, 1), date(2026, 11, 30))
    result = MonthlySpendMetric().evaluate(goal(), [evidence(15, "130.00", "food_groceries")], "2026-10")
    assert result["over_amount"] == Decimal("30.00")
    assert result["remaining"] == Decimal("0.00")


def test_goal_inputs_reject_non_money_and_invalid_status():
    for amount in ("0", "-1", "10.999"):
        with pytest.raises(ValidationError):
            GoalCreate(category_id="food_dining", threshold_amount=amount)
    with pytest.raises(ValidationError):
        GoalUpdate(status="deleted")
