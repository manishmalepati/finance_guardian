from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api.routes.budgets import MonthlyLimitInput, delete_monthly_limit, set_monthly_limit
from backend.db.models import CategoryTaxonomy, Goal


class FakeSession:
    def __init__(self, *categories: CategoryTaxonomy):
        self.categories = {category.category_id: category for category in categories}
        self.goal: Goal | None = None
        self.commits = 0

    def get(self, model, key):
        if model is CategoryTaxonomy:
            return self.categories.get(key)
        if model is Goal:
            return self.goal if self.goal and self.goal.id == key else None
        return None

    def scalar(self, _statement):
        return self.goal

    def add(self, row):
        row.id = str(uuid4())
        self.goal = row

    def delete(self, row):
        self.goal = None

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
    assert session.goal is None
    assert session.commits == 3


@pytest.mark.parametrize("category", [spending_category("income"), spending_category("financial")])
def test_monthly_limit_rejects_money_in_and_movements(category):
    with pytest.raises(HTTPException) as error:
        set_monthly_limit(category.category_id, MonthlyLimitInput(amount=Decimal("100.00")), FakeSession(category))

    assert error.value.status_code == 400


def test_monthly_limit_accepts_a_subcategory_and_reuses_goal_record():
    session = FakeSession(spending_category(), spending_category("food_groceries", "food_dining"))
    created = set_monthly_limit("food_groceries", MonthlyLimitInput(amount=Decimal("120.00")), session)
    existing_id = session.goal.id
    updated = set_monthly_limit("food_groceries", MonthlyLimitInput(amount=Decimal("140.00")), session)

    assert created == {"category_id": "food_groceries", "amount": Decimal("120.00")}
    assert updated["amount"] == Decimal("140.00")
    assert session.goal.id == existing_id
    assert session.goal.scope_kind == "subcategory"


def test_monthly_limit_must_be_positive_money():
    for amount in ["0", "-1", "12.345"]:
        with pytest.raises(ValidationError):
            MonthlyLimitInput(amount=amount)
