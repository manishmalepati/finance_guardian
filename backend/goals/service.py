"""Goal application service and persistence boundary."""

from __future__ import annotations

from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from backend.db.models import CategoryTaxonomy, Goal, Transaction, TransactionCategorization
from backend.goals.evaluation import EvidenceRow, METRICS, month_bounds


class GoalError(ValueError):
    pass


class GoalConflict(GoalError):
    pass


class GoalMissing(GoalError):
    pass


class GoalService:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[dict]:
        rows = self.session.scalars(select(Goal).order_by(Goal.created_at, Goal.name)).all()
        return [self.present(row) for row in rows]

    def get(self, goal_id: str) -> Goal:
        goal = self.session.get(Goal, goal_id)
        if goal is None:
            raise GoalMissing("Goal was not found.")
        return goal

    def find_monthly_scope(self, category_id: str) -> Goal | None:
        return self.session.scalar(select(Goal).where(
            Goal.metric_type == "monthly_spend", Goal.category_id == category_id,
        ))

    def validate_scope(self, category_id: str) -> tuple[CategoryTaxonomy, str]:
        category = self.session.get(CategoryTaxonomy, category_id)
        if category is None or not category.is_active:
            raise GoalError("Choose an active spending category or subcategory.")
        parent_id = category.parent_category_id or category.category_id
        if category.parent_category_id:
            parent = self.session.get(CategoryTaxonomy, parent_id)
            if parent is None or not parent.is_active:
                raise GoalError("Choose a subcategory under an active spending category.")
        if parent_id in {"income", "financial"}:
            raise GoalError("Money in and transfers cannot be spending goals.")
        return category, "subcategory" if category.parent_category_id else "category"

    @staticmethod
    def validate_timezone(value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
            raise GoalError("Choose a valid IANA time zone.") from exc
        return value

    def create(self, *, category_id: str, threshold_amount: Decimal, timezone: str,
               name: str | None = None, currency: str = "USD") -> dict:
        if threshold_amount <= 0:
            raise GoalError("The monthly threshold must be positive.")
        category, scope_kind = self.validate_scope(category_id)
        if self.find_monthly_scope(category_id):
            raise GoalConflict("A monthly spending goal already exists for this scope. Edit it instead.")
        goal = Goal(
            name=name or f"{category.display_name} monthly goal",
            metric_type="monthly_spend", period_type="calendar_month",
            scope_kind=scope_kind, category_id=category_id,
            threshold_amount=threshold_amount, currency=currency.upper(),
            timezone=self.validate_timezone(timezone), status="active", rule_version=1,
        )
        self.session.add(goal)
        self.session.commit()
        return self.present(goal)

    def update(self, goal_id: str, changes: dict) -> dict:
        goal = self.get(goal_id)
        if "threshold_amount" in changes and changes["threshold_amount"] <= 0:
            raise GoalError("The monthly threshold must be positive.")
        if "category_id" in changes:
            category, scope_kind = self.validate_scope(changes["category_id"])
            if category.category_id != goal.category_id and self.find_monthly_scope(category.category_id):
                raise GoalConflict("A monthly spending goal already exists for this scope.")
            goal.category_id = category.category_id
            goal.scope_kind = scope_kind
        if "timezone" in changes:
            goal.timezone = self.validate_timezone(changes["timezone"])
        for field in ("name", "threshold_amount", "currency", "status"):
            if field in changes:
                setattr(goal, field, changes[field].upper() if field == "currency" else changes[field])
        self.session.commit()
        return self.present(goal)

    def delete(self, goal_id: str) -> None:
        self.session.delete(self.get(goal_id))
        self.session.commit()

    def present(self, goal: Goal) -> dict:
        category = self.session.get(CategoryTaxonomy, goal.category_id)
        return {
            "id": goal.id, "name": goal.name, "metric_type": goal.metric_type,
            "period_type": goal.period_type, "scope_kind": goal.scope_kind,
            "category_id": goal.category_id,
            "category_name": category.display_name if category else goal.category_id,
            "threshold_amount": goal.threshold_amount, "currency": goal.currency,
            "timezone": goal.timezone, "status": goal.status,
            "rule_version": goal.rule_version,
        }

    def evaluate(self, goal: Goal, month: str | None = None) -> dict:
        first, last = month_bounds(month, goal.timezone)
        category = aliased(CategoryTaxonomy)
        statement = select(Transaction, TransactionCategorization.category_id, category.parent_category_id).outerjoin(
            TransactionCategorization,
            and_(TransactionCategorization.transaction_id == Transaction.id,
                 TransactionCategorization.status == "active"),
        ).outerjoin(category, category.category_id == TransactionCategorization.category_id).where(
            Transaction.status.in_(("active", "pending")),
            Transaction.posted_date >= first, Transaction.posted_date <= last,
        ).order_by(Transaction.posted_date.desc(), Transaction.id)
        seen: set[str] = set()
        rows = []
        for tx, category_id, parent_id in self.session.execute(statement).all():
            if tx.id in seen:
                continue
            seen.add(tx.id)
            rows.append(EvidenceRow(tx, category_id, parent_id))
        result = METRICS[goal.metric_type].evaluate(goal, rows, month)
        result["goal"] = self.present(goal)
        return result

    def evaluate_all(self, month: str | None = None) -> list[dict]:
        return [self.evaluate(goal, month) for goal in self.session.scalars(
            select(Goal).order_by(Goal.created_at, Goal.name)
        ).all()]
