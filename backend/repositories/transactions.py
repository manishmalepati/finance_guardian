from collections.abc import Sequence
from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.sql import Select
from sqlalchemy.orm import Session, aliased

from backend.db.models import CategoryTaxonomy, IngestionRun, Transaction, TransactionCategorization


class TransactionRepository:
    """Database access layer for raw transaction records."""

    def __init__(self, session: Session):
        self.session = session

    def list_transactions(
        self,
        limit: int = 100,
        start_date: date | None = None,
        end_date: date | None = None,
        query: str | None = None,
    ) -> Sequence[Transaction]:
        statement: Select[tuple[Transaction]] = select(Transaction).order_by(
            Transaction.posted_date.desc(), Transaction.created_at.desc()
        )
        if start_date:
            statement = statement.where(Transaction.posted_date >= start_date)
        if end_date:
            statement = statement.where(Transaction.posted_date <= end_date)
        if query:
            statement = statement.where(func.lower(Transaction.description).contains(query.lower()))
        return self.session.scalars(statement.limit(limit)).all()

    def list_transaction_details(
        self,
        limit: int = 100,
        start_date: date | None = None,
        end_date: date | None = None,
        query: str | None = None,
    ) -> Sequence[tuple[Transaction, TransactionCategorization | None, CategoryTaxonomy | None, CategoryTaxonomy | None]]:
        active_category = and_(
            TransactionCategorization.transaction_id == Transaction.id,
            TransactionCategorization.status == "active",
        )
        parent_category = aliased(CategoryTaxonomy)
        statement = (
            select(Transaction, TransactionCategorization, CategoryTaxonomy, parent_category)
            .outerjoin(TransactionCategorization, active_category)
            .outerjoin(CategoryTaxonomy, CategoryTaxonomy.category_id == TransactionCategorization.category_id)
            .outerjoin(parent_category, parent_category.category_id == CategoryTaxonomy.parent_category_id)
            .order_by(Transaction.posted_date.desc(), Transaction.created_at.desc())
        )
        if start_date:
            statement = statement.where(Transaction.posted_date >= start_date)
        if end_date:
            statement = statement.where(Transaction.posted_date <= end_date)
        if query:
            statement = statement.where(func.lower(Transaction.description).contains(query.lower()))
        return self.session.execute(statement.limit(limit)).all()

    def get_largest(self, limit: int = 10) -> Sequence[Transaction]:
        return self.session.scalars(
            select(Transaction).order_by(func.abs(Transaction.amount).desc()).limit(limit)
        ).all()

    def find_ingestion_run_by_fingerprint(self, source_fingerprint: str) -> IngestionRun | None:
        return self.session.scalar(select(IngestionRun).where(IngestionRun.source_fingerprint == source_fingerprint))
