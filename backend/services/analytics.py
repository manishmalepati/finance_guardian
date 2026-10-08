from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, extract, func, select
from sqlalchemy.orm import Session, aliased

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
        parent_category = aliased(CategoryTaxonomy)
        parent_category_id = func.coalesce(parent_category.category_id, "other")
        parent_category_name = func.coalesce(parent_category.display_name, "Other")
        subcategory_id = func.coalesce(CategoryTaxonomy.category_id, "other_uncategorized")
        subcategory_name = func.coalesce(CategoryTaxonomy.display_name, "Uncategorized")
        statement = select(
            parent_category_id.label("parent_category_id"),
            parent_category_name.label("parent_category"),
            subcategory_id.label("subcategory_id"),
            subcategory_name.label("subcategory"),
            func.sum(RawTransaction.amount).label("amount"),
            func.count().label("transaction_count"),
        ).outerjoin(TransactionCategorization, active_category).outerjoin(
            CategoryTaxonomy, CategoryTaxonomy.category_id == TransactionCategorization.category_id
        ).outerjoin(
            parent_category, parent_category.category_id == CategoryTaxonomy.parent_category_id
        ).where(RawTransaction.direction == "debit")
        if start_date:
            statement = statement.where(RawTransaction.posted_date >= start_date)
        if end_date:
            statement = statement.where(RawTransaction.posted_date <= end_date)
        rows = self.session.execute(
            statement.group_by(
                parent_category_id,
                parent_category_name,
                subcategory_id,
                subcategory_name,
            ).order_by(func.sum(RawTransaction.amount).desc())
        ).all()
        return [self._row_to_dict(row) for row in rows]

    def largest_transactions(self, limit: int = 10) -> list[dict]:
        active_category = and_(
            TransactionCategorization.transaction_id == RawTransaction.id,
            TransactionCategorization.status == "active",
        )
        parent_category = aliased(CategoryTaxonomy)
        rows = self.session.execute(
            select(RawTransaction, TransactionCategorization, CategoryTaxonomy, parent_category)
            .outerjoin(TransactionCategorization, active_category)
            .outerjoin(CategoryTaxonomy, CategoryTaxonomy.category_id == TransactionCategorization.category_id)
            .outerjoin(parent_category, parent_category.category_id == CategoryTaxonomy.parent_category_id)
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
                "category": parent.display_name if parent else "Uncategorized",
                "subcategory": category.display_name if category else None,
            }
            for transaction, categorization, category, parent in rows
        ]

    @staticmethod
    def _row_to_dict(row) -> dict:
        output = {}
        for key, value in row._mapping.items():
            output[key] = float(value) if isinstance(value, Decimal) else value
        return output
