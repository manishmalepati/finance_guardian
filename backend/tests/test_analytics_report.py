from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from backend.services.analytics import AnalyticsService


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _statement):
        return FakeResult(self.rows)


def row(month, category_id, parent_id, parent_name, direction, pending, amount):
    return SimpleNamespace(
        month=datetime(2026, month, 1), category_id=category_id,
        parent_id=parent_id, parent_name=parent_name,
        direction=direction, is_pending=pending, amount=Decimal(amount),
    )


def test_spending_report_separates_pending_activity_and_money_movements():
    rows = [
        row(9, "food_groceries", "food_dining", "Food & Dining", "debit", False, "20.00"),
        row(10, "food_groceries", "food_dining", "Food & Dining", "debit", True, "5.00"),
        row(10, None, "other", "Other", "debit", False, "3.00"),
        row(10, "income_paycheck", "income", "Income", "credit", False, "100.00"),
        row(10, "financial_transfers", "financial", "Financial", "debit", False, "80.00"),
        row(10, "financial_credit_card_payment", "financial", "Financial", "debit", True, "10.00"),
        row(10, "financial_transfers", "financial", "Financial", "credit", False, "15.00"),
    ]

    report = AnalyticsService(FakeSession(rows)).spending_report(date(2026, 8, 1), date(2026, 10, 31))

    assert report["summary"] == {
        "posted_spending": 23.0, "pending_spending": 5.0,
        "posted_money_in": 100.0, "pending_money_in": 0.0,
        "posted_movements_out": 80.0, "pending_movements_out": 10.0,
        "posted_movements_in": 15.0, "pending_movements_in": 0.0,
    }
    assert [month["month"] for month in report["months"]] == ["2026-08-01", "2026-09-01", "2026-10-01"]
    assert report["months"][0]["posted_spending"] == 0.0
    assert report["months"][2]["posted_spending"] == 3.0
    assert report["categories"] == [
        {"parent_category_id": "food_dining", "parent_category": "Food & Dining", "posted_amount": 20.0, "pending_amount": 5.0},
        {"parent_category_id": "other", "parent_category": "Other", "posted_amount": 3.0, "pending_amount": 0.0},
    ]
    assert len(report["category_months"]) == 3
    assert all(item["parent_category_id"] != "financial" for item in report["category_months"])
