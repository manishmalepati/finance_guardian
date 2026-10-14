from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, extract, func, or_, select
from sqlalchemy.orm import Session, aliased

from backend.db.models import CategoryTaxonomy, Transaction, TransactionCategorization
from backend.domain.money_flow import MOVEMENT_CATEGORY_IDS


class AnalyticsService:
    """Read-only finance analytics backed by SQL aggregates."""

    def __init__(self, session: Session):
        self.session = session

    def monthly_summary(self) -> list[dict]:
        active_category = and_(
            TransactionCategorization.transaction_id == Transaction.id,
            TransactionCategorization.status == "active",
        )
        signed_amount = case(
            (Transaction.direction == "debit", Transaction.amount),
            else_=-Transaction.amount,
        )
        posted_filter = Transaction.is_pending.is_(False)
        pending_filter = Transaction.is_pending.is_(True)
        rows = self.session.execute(
            select(
                extract("year", Transaction.posted_date).label("year"),
                extract("month", Transaction.posted_date).label("month"),
                func.sum(case((Transaction.direction == "debit", Transaction.amount), else_=0)).label("debits"),
                func.sum(case((Transaction.direction == "credit", Transaction.amount), else_=0)).label("credits"),
                func.sum(signed_amount).label("net_spend"),
                func.sum(
                    case((and_(Transaction.direction == "debit", posted_filter), Transaction.amount), else_=0)
                ).label("posted_debits"),
                func.sum(
                    case((and_(Transaction.direction == "credit", posted_filter), Transaction.amount), else_=0)
                ).label("posted_credits"),
                func.sum(case((posted_filter, signed_amount), else_=0)).label("posted_net_spend"),
                func.sum(
                    case((and_(Transaction.direction == "debit", pending_filter), Transaction.amount), else_=0)
                ).label("pending_debits"),
                func.sum(
                    case((and_(Transaction.direction == "credit", pending_filter), Transaction.amount), else_=0)
                ).label("pending_credits"),
                func.sum(case((pending_filter, signed_amount), else_=0)).label("pending_net_spend"),
                func.count().label("transaction_count"),
                func.sum(case((posted_filter, 1), else_=0)).label("posted_transaction_count"),
                func.sum(case((pending_filter, 1), else_=0)).label("pending_transaction_count"),
            )
            .outerjoin(TransactionCategorization, active_category)
            .group_by("year", "month")
            .where(
                Transaction.status.in_(["active", "pending"]),
                or_(
                    TransactionCategorization.category_id.is_(None),
                    TransactionCategorization.category_id.notin_(MOVEMENT_CATEGORY_IDS),
                ),
            )
            .order_by("year", "month")
        ).all()
        return [self._row_to_dict(row) for row in rows]

    def category_spending(self, start_date: date | None = None, end_date: date | None = None) -> list[dict]:
        active_category = and_(
            TransactionCategorization.transaction_id == Transaction.id,
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
            func.sum(Transaction.amount).label("amount"),
            func.sum(case((Transaction.is_pending.is_(False), Transaction.amount), else_=0)).label("posted_amount"),
            func.sum(case((Transaction.is_pending.is_(True), Transaction.amount), else_=0)).label("pending_amount"),
            func.count().label("transaction_count"),
            func.sum(case((Transaction.is_pending.is_(False), 1), else_=0)).label("posted_transaction_count"),
            func.sum(case((Transaction.is_pending.is_(True), 1), else_=0)).label("pending_transaction_count"),
        ).outerjoin(TransactionCategorization, active_category).outerjoin(
            CategoryTaxonomy, CategoryTaxonomy.category_id == TransactionCategorization.category_id
        ).outerjoin(
            parent_category, parent_category.category_id == CategoryTaxonomy.parent_category_id
        ).where(
            Transaction.direction == "debit",
            Transaction.status.in_(["active", "pending"]),
            or_(
                TransactionCategorization.category_id.is_(None),
                TransactionCategorization.category_id.notin_(MOVEMENT_CATEGORY_IDS),
            ),
        )
        if start_date:
            statement = statement.where(Transaction.posted_date >= start_date)
        if end_date:
            statement = statement.where(Transaction.posted_date <= end_date)
        rows = self.session.execute(
            statement.group_by(
                parent_category_id,
                parent_category_name,
                subcategory_id,
                subcategory_name,
            ).order_by(func.sum(Transaction.amount).desc())
        ).all()
        return [self._row_to_dict(row) for row in rows]

    def spending_report(self, start_date: date, end_date: date, account_id: str | None = None) -> dict:
        """Account-aware monthly aggregates for all report visuals."""
        active_category = and_(
            TransactionCategorization.transaction_id == Transaction.id,
            TransactionCategorization.status == "active",
        )
        parent = aliased(CategoryTaxonomy)
        month = func.date_trunc("month", Transaction.posted_date)
        parent_id = func.coalesce(parent.category_id, "other")
        parent_name = func.coalesce(parent.display_name, "Other")
        statement = (
            select(
                month.label("month"),
                TransactionCategorization.category_id.label("category_id"),
                parent_id.label("parent_id"),
                parent_name.label("parent_name"),
                Transaction.direction,
                Transaction.is_pending,
                func.sum(Transaction.amount).label("amount"),
            )
            .select_from(Transaction)
            .outerjoin(TransactionCategorization, active_category)
            .outerjoin(CategoryTaxonomy, CategoryTaxonomy.category_id == TransactionCategorization.category_id)
            .outerjoin(parent, parent.category_id == CategoryTaxonomy.parent_category_id)
            .where(
                Transaction.status.in_(["active", "pending"]),
                Transaction.posted_date >= start_date,
                Transaction.posted_date <= end_date,
            )
            .group_by(
                month, TransactionCategorization.category_id, parent_id, parent_name,
                Transaction.direction, Transaction.is_pending,
            )
            .order_by(month)
        )
        if account_id:
            statement = statement.where(Transaction.account_id == account_id)

        measure_names = (
            "posted_spending", "pending_spending", "posted_money_in", "pending_money_in",
            "posted_movements_out", "pending_movements_out", "posted_movements_in", "pending_movements_in",
        )

        def empty_measures() -> dict[str, Decimal]:
            return {name: Decimal("0") for name in measure_names}

        summary = empty_measures()
        months: dict[str, dict[str, Decimal]] = {}
        categories: dict[str, dict] = {}
        category_months: dict[tuple[str, str], dict] = {}
        for row in self.session.execute(statement).all():
            month_key = date(row.month.year, row.month.month, 1).isoformat()
            month_bucket = months.setdefault(month_key, empty_measures())
            amount = row.amount
            direction = "out" if row.direction == "debit" else "in"
            if row.category_id in MOVEMENT_CATEGORY_IDS:
                measure = f"{'pending' if row.is_pending else 'posted'}_movements_{direction}"
            elif row.direction == "debit":
                measure = f"{'pending' if row.is_pending else 'posted'}_spending"
            else:
                measure = f"{'pending' if row.is_pending else 'posted'}_money_in"
            summary[measure] += amount
            month_bucket[measure] += amount

            if row.direction != "debit" or row.category_id in MOVEMENT_CATEGORY_IDS:
                continue
            category = categories.setdefault(row.parent_id, {
                "parent_category_id": row.parent_id,
                "parent_category": row.parent_name,
                "posted_amount": Decimal("0"), "pending_amount": Decimal("0"),
            })
            category_month = category_months.setdefault((month_key, row.parent_id), {
                "month": month_key,
                "parent_category_id": row.parent_id,
                "parent_category": row.parent_name,
                "posted_amount": Decimal("0"), "pending_amount": Decimal("0"),
            })
            amount_key = "pending_amount" if row.is_pending else "posted_amount"
            category[amount_key] += amount
            category_month[amount_key] += amount

        def as_numbers(values: dict) -> dict:
            return {key: float(value) if isinstance(value, Decimal) else value for key, value in values.items()}

        complete_months = []
        year, month_number = start_date.year, start_date.month
        while (year, month_number) <= (end_date.year, end_date.month):
            month_key = date(year, month_number, 1).isoformat()
            complete_months.append({"month": month_key, **as_numbers(months.get(month_key, empty_measures()))})
            if month_number == 12:
                year, month_number = year + 1, 1
            else:
                month_number += 1

        return {
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
            "account_id": account_id,
            "summary": as_numbers(summary),
            "months": complete_months,
            "categories": sorted(
                (as_numbers(value) for value in categories.values()),
                key=lambda row: row["posted_amount"] + row["pending_amount"], reverse=True,
            ),
            "category_months": [as_numbers(value) for _, value in sorted(category_months.items())],
        }

    def largest_transactions(self, limit: int = 10) -> list[dict]:
        active_category = and_(
            TransactionCategorization.transaction_id == Transaction.id,
            TransactionCategorization.status == "active",
        )
        parent_category = aliased(CategoryTaxonomy)
        rows = self.session.execute(
            select(Transaction, TransactionCategorization, CategoryTaxonomy, parent_category)
            .outerjoin(TransactionCategorization, active_category)
            .outerjoin(CategoryTaxonomy, CategoryTaxonomy.category_id == TransactionCategorization.category_id)
            .outerjoin(parent_category, parent_category.category_id == CategoryTaxonomy.parent_category_id)
            .where(Transaction.status.in_(["active", "pending"]))
            .order_by(Transaction.amount.desc())
            .limit(limit)
        ).all()
        return [
            {
                "id": transaction.id,
                "posted_date": transaction.posted_date.isoformat(),
                "description": transaction.description,
                "amount": transaction.amount,
                "direction": transaction.direction,
                "is_pending": transaction.is_pending,
                "status": transaction.status,
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
