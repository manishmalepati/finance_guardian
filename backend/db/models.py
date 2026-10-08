from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
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


class CategoryTaxonomy(Base):
    __tablename__ = "category_taxonomy"
    __table_args__ = {"schema": "enrichment"}

    category_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    parent_category_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("enrichment.category_taxonomy.category_id"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MerchantAlias(Base):
    __tablename__ = "merchant_aliases"
    __table_args__ = (
        UniqueConstraint("normalized_pattern", name="uq_merchant_alias_normalized_pattern"),
        {"schema": "enrichment"},
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    normalized_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_merchant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("enrichment.category_taxonomy.category_id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=Decimal("1.000"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CategorizationJob(Base):
    __tablename__ = "categorization_jobs"
    __table_args__ = (
        UniqueConstraint("normalized_merchant", name="uq_categorization_job_normalized_merchant"),
        {"schema": "enrichment"},
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    normalized_merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    example_descriptions: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TransactionCategorization(Base):
    __tablename__ = "transaction_categorizations"
    __table_args__ = {"schema": "enrichment"}

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    transaction_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("raw.statement_transactions.id"), nullable=False
    )
    normalized_merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_merchant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("enrichment.category_taxonomy.category_id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=Decimal("1.000"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
