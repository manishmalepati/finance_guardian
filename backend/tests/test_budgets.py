from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api.routes.budgets import MonthlyLimitInput, delete_monthly_limit, set_monthly_limit
from backend.db.models import CategoryTaxonomy, MonthlyCategoryLimit


class FakeSession:
    def __init__(self, category: CategoryTaxonomy | None = None):
        self.category = category
        self.limit: MonthlyCategoryLimit | None = None
        self.commits = 0

    def get(self, model, key):
        if model is CategoryTaxonomy:
            return self.category if self.category and self.category.category_id == key else None
        if model is MonthlyCategoryLimit:
            return self.limit if self.limit and self.limit.category_id == key else None
        return None

    def add(self, row):
        self.limit = row

    def delete(self, row):
        self.limit = None

    def commit(self):
        self.commits += 1


def spending_category(category_id="food_dining", parent_category_id=None):
    return CategoryTaxonomy(
        category_id=category_id,
        parent_category_id=parent_category_id,
        display_name="Food & Dining",
        level=1 if parent_category_id is None else 2,
        sort_order=1,
        is_active=True,
    )


def test_monthly_limit_can_be_created_updated_and_removed():
    session = FakeSession(spending_category())

    created = set_monthly_limit("food_dining", MonthlyLimitInput(amount=Decimal("450.00")), session)
    updated = set_monthly_limit("food_dining", MonthlyLimitInput(amount=Decimal("500.00")), session)
    delete_monthly_limit("food_dining", session)

    assert created == {"category_id": "food_dining", "amount": Decimal("450.00")}
    assert updated == {"category_id": "food_dining", "amount": Decimal("500.00")}
    assert session.limit is None
    assert session.commits == 3


@pytest.mark.parametrize("category", [spending_category("income"), spending_category("food_groceries", "food_dining")])
def test_monthly_limit_requires_parent_spending_category(category):
    with pytest.raises(HTTPException) as error:
        set_monthly_limit(category.category_id, MonthlyLimitInput(amount=Decimal("100.00")), FakeSession(category))

    assert error.value.status_code == 400


def test_monthly_limit_must_be_positive_money():
    for amount in ["0", "-1", "12.345"]:
        with pytest.raises(ValidationError):
            MonthlyLimitInput(amount=amount)
