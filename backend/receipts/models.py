from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ReceiptBase(DeclarativeBase):
    pass


def new_id() -> str:
    return str(uuid4())


class GmailConnection(ReceiptBase):
    __tablename__ = "gmail_connections"
    __table_args__ = {"schema": "receipt"}

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    email_address: Mapped[str] = mapped_column(Text, unique=True)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="active")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OAuthState(ReceiptBase):
    __tablename__ = "oauth_states"
    __table_args__ = {"schema": "receipt"}

    state: Mapped[str] = mapped_column(Text, primary_key=True)
    code_verifier: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GmailSyncRun(ReceiptBase):
    __tablename__ = "sync_runs"
    __table_args__ = {"schema": "receipt"}

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    status: Mapped[str] = mapped_column(String(30))
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailSource(ReceiptBase):
    __tablename__ = "email_sources"
    __table_args__ = (UniqueConstraint("connection_id", "gmail_message_id"), {"schema": "receipt"})

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    gmail_message_id: Mapped[str] = mapped_column(Text)
    sender: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parse_status: Mapped[str] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(100))
    parser_version: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(ReceiptBase):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("email_source_id", "order_index"), {"schema": "receipt"})

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    email_source_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    merchant: Mapped[str] = mapped_column(Text)
    merchant_order_id: Mapped[str | None] = mapped_column(Text)
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    placed_date: Mapped[date | None] = mapped_column()
    currency: Mapped[str | None] = mapped_column(String(10))
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    delivery_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    tax: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    tip: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    other_fees: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    parse_quality: Mapped[str] = mapped_column(String(30))


class OrderItem(ReceiptBase):
    __tablename__ = "order_items"
    __table_args__ = (UniqueConstraint("order_id", "position"), {"schema": "receipt"})

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    category_id: Mapped[str | None] = mapped_column(String(50))
    evidence: Mapped[str | None] = mapped_column(Text)


class TransactionOrderMatch(ReceiptBase):
    __tablename__ = "transaction_order_matches"
    __table_args__ = (UniqueConstraint("transaction_id", "order_id"), {"schema": "receipt"})

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    transaction_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    order_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    status: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    user_override: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
