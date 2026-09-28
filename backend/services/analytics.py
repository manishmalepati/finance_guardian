from datetime import date
from decimal import Decimal

from sqlalchemy import case, extract, func, select
from sqlalchemy.orm import Session

from backend.db.models import RawTransaction


class AnalyticsService:
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
        statement = select(
            func.coalesce(RawTransaction.category_hint, "Uncategorized").label("category"),
            func.sum(RawTransaction.amount).label("amount"),
            func.count().label("transaction_count"),
        ).where(RawTransaction.direction == "debit")
        if start_date:
            statement = statement.where(RawTransaction.posted_date >= start_date)
        if end_date:
            statement = statement.where(RawTransaction.posted_date <= end_date)
        rows = self.session.execute(statement.group_by("category").order_by(func.sum(RawTransaction.amount).desc())).all()
        return [self._row_to_dict(row) for row in rows]

    def largest_transactions(self, limit: int = 10) -> list[dict]:
        rows = self.session.scalars(
            select(RawTransaction).order_by(RawTransaction.amount.desc()).limit(limit)
        ).all()
        return [
            {
                "id": row.id,
                "posted_date": row.posted_date.isoformat(),
                "description": row.description,
                "amount": row.amount,
                "direction": row.direction,
            }
            for row in rows
        ]

    @staticmethod
    def _row_to_dict(row) -> dict:
        output = {}
        for key, value in row._mapping.items():
            output[key] = float(value) if isinstance(value, Decimal) else value
        return output
