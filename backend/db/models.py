from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class StatementImport(Base):
    __tablename__ = "statement_imports"
    __table_args__ = {"schema": "raw"}

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    transactions: Mapped[list["RawTransaction"]] = relationship(back_populates="statement_import")


class RawTransaction(Base):
    __tablename__ = "statement_transactions"
    __table_args__ = (
        UniqueConstraint("statement_import_id", "source_transaction_key", name="uq_statement_transaction_source_key"),
        {"schema": "raw"},
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    statement_import_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("raw.statement_imports.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_transaction_key: Mapped[str] = mapped_column(String(255), nullable=False)
    posted_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Chase")
    category_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    row_number: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    statement_import: Mapped[StatementImport] = relationship(back_populates="transactions")
