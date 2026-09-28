from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.sql import Select
from sqlalchemy.orm import Session

from backend.db.models import RawTransaction, StatementImport


class TransactionRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_transactions(
        self,
        limit: int = 100,
        start_date: date | None = None,
        end_date: date | None = None,
        query: str | None = None,
    ) -> Sequence[RawTransaction]:
        statement: Select[tuple[RawTransaction]] = select(RawTransaction).order_by(
            RawTransaction.posted_date.desc(), RawTransaction.created_at.desc()
        )
        if start_date:
            statement = statement.where(RawTransaction.posted_date >= start_date)
        if end_date:
            statement = statement.where(RawTransaction.posted_date <= end_date)
        if query:
            statement = statement.where(func.lower(RawTransaction.description).contains(query.lower()))
        return self.session.scalars(statement.limit(limit)).all()

    def get_largest(self, limit: int = 10) -> Sequence[RawTransaction]:
        return self.session.scalars(
            select(RawTransaction).order_by(func.abs(RawTransaction.amount).desc()).limit(limit)
        ).all()

    def find_import_by_hash(self, file_hash: str) -> StatementImport | None:
        return self.session.scalar(select(StatementImport).where(StatementImport.file_hash == file_hash))
