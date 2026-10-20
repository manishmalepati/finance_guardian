"""Sanitized, repeatable vertical-slice data for a separate demo database."""

import base64
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import FinancialAccount, IngestionRun, Transaction
from backend.core.config import settings
from backend.receipts.gmail_sync import GmailSync
from backend.receipts.models import EmailSource, GmailConnection
from backend.receipts.parser import parse_receipt
from backend.services.categorization import CategorizationService

DEMO_SOURCE_KEY = "synthetic-doordash-2026-10-13"
DEMO_MESSAGE_ID = "synthetic-doordash-message-1"
UBER_SOURCE_KEY = "synthetic-ubereats-2026-10-15"
UBER_MESSAGE_ID = "synthetic-ubereats-message-1"
DEMO_RECEIPT = """Order #DEMO-12345
Order placed: 2026-10-12 19:30:00-07:00
1 x Veggie Bowl USD $14.00
2 x Sparkling Water USD $6.00
Subtotal USD $20.00
Delivery fee USD $2.00
Tax USD $1.50
Tip USD $3.50
Total USD $27.00
"""
UBER_RECEIPT = """Oct 14, 2026
Your order with Uber Eats
Order details
1 x Noodle Bowl USD $12.00
1 x Iced Tea USD $3.00
Subtotal USD $15.00
Delivery fee USD $1.50
Tax USD $1.00
Tip USD $2.00
Total USD $19.50
"""


def demo_message() -> dict:
    return {
        "internalDate": "1791871200000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "DoorDash <orders@doordash.com>"},
                {"name": "Subject", "value": "Your DoorDash order receipt"},
            ],
            "body": {"data": base64.urlsafe_b64encode(DEMO_RECEIPT.encode()).decode().rstrip("=")},
        },
    }


def uber_demo_message() -> dict:
    return {
        "internalDate": "1792044000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Uber Eats <noreply@uber.com>"},
                {"name": "Subject", "value": "Your Market Kitchen order with Uber Eats"},
            ],
            "body": {"data": base64.urlsafe_b64encode(UBER_RECEIPT.encode()).decode().rstrip("=")},
        },
    }


def _seed_uber_demo(session: Session) -> None:
    existing = session.scalar(select(Transaction).where(
        Transaction.source == "demo",
        Transaction.source_transaction_key == UBER_SOURCE_KEY,
    ))
    if existing is not None:
        return
    baseline = session.scalar(select(Transaction).where(
        Transaction.source == "demo",
        Transaction.source_transaction_key == DEMO_SOURCE_KEY,
    ))
    connection = session.scalar(select(GmailConnection).where(GmailConnection.email_address == "demo@example.invalid"))
    session.add(Transaction(
        ingestion_run_id=baseline.ingestion_run_id, account_id=baseline.account_id,
        source="demo", source_transaction_key=UBER_SOURCE_KEY,
        posted_date=date(2026, 10, 15), authorized_date=date(2026, 10, 14),
        description="UBER EATS DEMO", merchant_name="Uber Eats",
        amount=Decimal("19.50"), direction="debit",
        account_name="Demo checking", iso_currency_code="USD",
        is_pending=False, status="active",
    ))
    session.flush()
    CategorizationService(session).apply_known_aliases_and_queue_unknowns(commit=False)
    message = uber_demo_message()
    GmailSync(session)._persist(connection, UBER_MESSAGE_ID, message, parse_receipt(message), None)
    session.commit()


def seed_demo(session: Session) -> None:
    """Called only when DEMO_MODE is set on the isolated demo stack."""
    if not settings.database_url.rsplit("/", 1)[-1].startswith("finance_guardian_demo"):
        raise RuntimeError("Demo seeding requires a finance_guardian_demo database.")
    existing = session.scalar(select(Transaction).where(
        Transaction.source == "demo",
        Transaction.source_transaction_key == DEMO_SOURCE_KEY,
    ))
    if existing is not None:
        _seed_uber_demo(session)
        return
    ingestion = IngestionRun(
        source="demo", filename="synthetic-fixture",
        source_fingerprint="demo-fixture-v1", status="completed",
    )
    account = FinancialAccount(
        source="demo", source_account_key="demo-checking",
        name="Demo checking", account_type="depository",
        iso_currency_code="USD",
    )
    session.add_all((ingestion, account))
    session.flush()
    session.add(Transaction(
        ingestion_run_id=ingestion.id, account_id=account.id,
        source="demo", source_transaction_key=DEMO_SOURCE_KEY,
        posted_date=date(2026, 10, 13), authorized_date=date(2026, 10, 12),
        description="DOORDASH DEMO", merchant_name="DoorDash",
        amount=Decimal("27.00"), direction="debit",
        account_name="Demo checking", iso_currency_code="USD",
        is_pending=False, status="active",
    ))
    session.flush()
    CategorizationService(session).apply_known_aliases_and_queue_unknowns(commit=False)
    connection = GmailConnection(
        email_address="demo@example.invalid",
        encrypted_refresh_token="", status="demo",
    )
    session.add(connection)
    session.flush()
    message = demo_message()
    GmailSync(session)._persist(connection, DEMO_MESSAGE_ID, message, parse_receipt(message), None)
    session.commit()
    _seed_uber_demo(session)
