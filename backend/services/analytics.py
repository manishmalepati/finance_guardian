from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, extract, func, select
from sqlalchemy.orm import Session

from backend.db.models import CategoryTaxonomy, RawTransaction, TransactionCategorization


class AnalyticsService:
    """Read-only finance analytics backed by SQL aggregates."""

    def __init__(self, session: Session):
        self.session = session

    def monthly_summary(self) -> list[dict]:
        signed_amount = case(
            (RawTransaction.direction == "debit", RawTransaction.amount),
            else_=-RawTransaction.amount,
        )
        rows = self.session.execute(
            select(
                extract("year", RawTransaction.posted_date).label("year"),
                extract("month", RawTransaction.posted_date).label("month"),
                func.sum(case((RawTransaction.direction == "debit", RawTransaction.amount), else_=0)).label("debits"),
                func.sum(case((RawTransaction.direction == "credit", RawTransaction.amount), else_=0)).label("credits"),
                func.sum(signed_amount).label("net_spend"),
                func.count().label("transaction_count"),
            )
            .group_by("year", "month")
            .order_by("year", "month")
        ).all()
        return [self._row_to_dict(row) for row in rows]

    def category_spending(self, start_date: date | None = None, end_date: date | None = None) -> list[dict]:
        active_category = and_(
            TransactionCategorization.transaction_id == RawTransaction.id,
            TransactionCategorization.status == "active",
        )
        statement = select(
            func.coalesce(CategoryTaxonomy.display_name, "Uncategorized").label("category"),
            func.sum(RawTransaction.amount).label("amount"),
            func.count().label("transaction_count"),
        ).outerjoin(TransactionCategorization, active_category).outerjoin(
            CategoryTaxonomy, CategoryTaxonomy.category_id == TransactionCategorization.category_id
        ).where(RawTransaction.direction == "debit")
        if start_date:
            statement = statement.where(RawTransaction.posted_date >= start_date)
        if end_date:
            statement = statement.where(RawTransaction.posted_date <= end_date)
        rows = self.session.execute(statement.group_by("category").order_by(func.sum(RawTransaction.amount).desc())).all()
        return [self._row_to_dict(row) for row in rows]

    def largest_transactions(self, limit: int = 10) -> list[dict]:
        active_category = and_(
            TransactionCategorization.transaction_id == RawTransaction.id,
            TransactionCategorization.status == "active",
        )
        rows = self.session.execute(
            select(RawTransaction, TransactionCategorization, CategoryTaxonomy)
            .outerjoin(TransactionCategorization, active_category)
            .outerjoin(CategoryTaxonomy, CategoryTaxonomy.category_id == TransactionCategorization.category_id)
            .order_by(RawTransaction.amount.desc())
            .limit(limit)
        ).all()
        return [
            {
                "id": transaction.id,
                "posted_date": transaction.posted_date.isoformat(),
                "description": transaction.description,
                "amount": transaction.amount,
                "direction": transaction.direction,
                "merchant": categorization.canonical_merchant_name if categorization else None,
                "category": category.display_name if category else "Uncategorized",
            }
            for transaction, categorization, category in rows
        ]

    @staticmethod
    def _row_to_dict(row) -> dict:
        output = {}
        for key, value in row._mapping.items():
            output[key] = float(value) if isinstance(value, Decimal) else value
        return output
