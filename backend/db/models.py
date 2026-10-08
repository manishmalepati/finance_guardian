from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = {"schema": "raw"}

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    transactions: Mapped[list["RawTransaction"]] = relationship(back_populates="ingestion_run")


class RawTransaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("source", "source_transaction_key", name="uq_transaction_source_key"),
        {"schema": "raw"},
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    ingestion_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("raw.ingestion_runs.id"), nullable=False
    )
    account_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("raw.financial_accounts.id"), nullable=True)
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

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="transactions")
    account: Mapped["FinancialAccount | None"] = relationship(back_populates="transactions")


class PlaidItem(Base):
    __tablename__ = "plaid_items"
    __table_args__ = {"schema": "raw"}

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    item_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    institution_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    institution_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    accounts: Mapped[list["FinancialAccount"]] = relationship(back_populates="plaid_item")


class FinancialAccount(Base):
    __tablename__ = "financial_accounts"
    __table_args__ = (
        UniqueConstraint("source", "source_account_key", name="uq_financial_account_source_key"),
        {"schema": "raw"},
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_account_key: Mapped[str] = mapped_column(String(255), nullable=False)
    plaid_item_id: Mapped[str | None] = mapped_column(String(255), ForeignKey("raw.plaid_items.item_id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    official_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mask: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    account_subtype: Mapped[str | None] = mapped_column(String(50), nullable=True)
    available_balance: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_balance: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    iso_currency_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    plaid_item: Mapped[PlaidItem | None] = relationship(back_populates="accounts")
    transactions: Mapped[list[RawTransaction]] = relationship(back_populates="account")


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
        UUID(as_uuid=False), ForeignKey("raw.transactions.id"), nullable=False
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
