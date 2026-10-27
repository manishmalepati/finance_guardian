"""Synthetic reconciliation scenarios against the isolated demo database."""

import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from backend.db.models import IngestionRun, Transaction
from backend.receipts.context import confirm_match, unlink_match
from backend.receipts.models import EmailSource, GmailConnection, Order, TransactionOrderMatch
from backend.receipts.reconciliation import ReceiptReconciler


def test_delayed_split_combined_refund_and_user_decisions():
    url = os.getenv("FG_DEMO_DATABASE_URL")
    if not url:
        pytest.skip("Set FG_DEMO_DATABASE_URL to run the PostgreSQL reconciliation check.")
    if not url.rsplit("/", 1)[-1].startswith("finance_guardian_demo"):
        pytest.fail("FG_DEMO_DATABASE_URL must target the isolated demo database.")

    engine = create_engine(url)
    tag = uuid4().hex
    order_ids: list[str] = []
    transaction_ids: list[str] = []
    source_ids: list[str] = []
    connection_id = ingestion_id = None

    try:
        with Session(engine) as session:
            ingestion = IngestionRun(
                source="test", filename="synthetic-reconciliation",
                source_fingerprint=f"test-reconciliation-{tag}", status="completed",
            )
            connection = GmailConnection(
                email_address=f"reconcile-{tag}@example.invalid",
                encrypted_refresh_token="synthetic-only", status="demo",
            )
            session.add_all((ingestion, connection))
            session.flush()
            ingestion_id, connection_id = ingestion.id, connection.id

            def make_order(label: str, day: int, total: str) -> Order:
                source = EmailSource(
                    connection_id=connection.id, gmail_message_id=f"{tag}-{label}",
                    parse_status="complete", parser_version="test",
                )
                session.add(source)
                session.flush()
                source_ids.append(source.id)
                order = Order(
                    email_source_id=source.id, order_index=0, merchant="DoorDash",
                    placed_date=date(2026, 6, day), total=Decimal(total),
                    currency="USD", parse_quality="complete",
                )
                session.add(order)
                session.flush()
                order_ids.append(order.id)
                return order

            def make_transaction(label: str, day: int, total: str, direction: str = "debit") -> Transaction:
                transaction = Transaction(
                    ingestion_run_id=ingestion.id, source="test",
                    source_transaction_key=f"{tag}-{label}",
                    posted_date=date(2026, 6, day), authorized_date=date(2026, 6, day),
                    description="DOORDASH TEST", merchant_name="DoorDash",
                    amount=Decimal(total), direction=direction,
                    account_name="Synthetic test account", iso_currency_code="USD",
                    is_pending=False, status="active",
                )
                session.add(transaction)
                session.flush()
                transaction_ids.append(transaction.id)
                return transaction

            delayed = make_order("delayed", 1, "27.00")
            reconciler = ReceiptReconciler(session)
            assert reconciler.reconcile_order(delayed) == {"created": 0, "updated": 0}
            late_charge = make_transaction("late", 8, "27.00")
            late_charge.authorized_date = date(2026, 6, 1)
            assert reconciler.reconcile_all()["links_created"] >= 1
            delayed_match = session.scalar(select(TransactionOrderMatch).where(
                TransactionOrderMatch.order_id == delayed.id,
            ))
            assert delayed_match.transaction_id == late_charge.id
            assert delayed_match.status == "confirmed"
            assert reconciler.reconcile_order(delayed) == {"created": 0, "updated": 0}

            first_duplicate = make_order("same-total-one", 10, "40.00")
            duplicate_charge = make_transaction("same-total", 10, "40.00")
            assert reconciler.reconcile_order(first_duplicate)["created"] == 1
            second_duplicate = make_order("same-total-two", 10, "40.00")
            reconciler.reconcile_all()
            duplicate_links = session.scalars(select(TransactionOrderMatch).where(
                TransactionOrderMatch.transaction_id == duplicate_charge.id,
                TransactionOrderMatch.order_id.in_((first_duplicate.id, second_duplicate.id)),
            )).all()
            assert len(duplicate_links) == 2
            assert {row.status for row in duplicate_links} == {"suggested"}
            assert reconciler.reconcile_order(first_duplicate) == {"created": 0, "updated": 0}

            split_order = make_order("split", 17, "30.00")
            first_charge = make_transaction("split-one", 17, "18.00")
            second_charge = make_transaction("split-two", 17, "12.00")
            assert reconciler.reconcile_order(split_order)["created"] == 0
            confirm_match(session, first_charge.id, split_order.id)
            confirm_match(session, second_charge.id, split_order.id)
            assert reconciler.reconcile_order(split_order) == {"created": 0, "updated": 0}
            assert {row.transaction_id for row in session.scalars(select(TransactionOrderMatch).where(
                TransactionOrderMatch.order_id == split_order.id,
                TransactionOrderMatch.status == "confirmed",
            )).all()} == {first_charge.id, second_charge.id}

            first_order = make_order("combined-one", 25, "11.00")
            second_order = make_order("combined-two", 25, "19.00")
            combined_charge = make_transaction("combined", 25, "30.00")
            assert reconciler.reconcile_order(first_order)["created"] == 0
            assert reconciler.reconcile_order(second_order)["created"] == 0
            confirm_match(session, combined_charge.id, first_order.id)
            confirm_match(session, combined_charge.id, second_order.id)
            assert {row.order_id for row in session.scalars(select(TransactionOrderMatch).where(
                TransactionOrderMatch.transaction_id == combined_charge.id,
                TransactionOrderMatch.status == "confirmed",
            )).all()} == {first_order.id, second_order.id}

            refund_order = make_order("refund", 29, "14.00")
            make_transaction("refund", 29, "14.00", direction="credit")
            assert reconciler.reconcile_order(refund_order)["created"] == 0

            unlink_match(session, late_charge.id, delayed_match.id)
            assert reconciler.reconcile_order(delayed) == {"created": 0, "updated": 0}
            assert delayed_match.status == "rejected"
    finally:
        if connection_id:
            with Session(engine) as session:
                if order_ids:
                    session.execute(delete(TransactionOrderMatch).where(TransactionOrderMatch.order_id.in_(order_ids)))
                    session.execute(delete(Order).where(Order.id.in_(order_ids)))
                if source_ids:
                    session.execute(delete(EmailSource).where(EmailSource.id.in_(source_ids)))
                if transaction_ids:
                    session.execute(delete(Transaction).where(Transaction.id.in_(transaction_ids)))
                session.execute(delete(GmailConnection).where(GmailConnection.id == connection_id))
                if ingestion_id:
                    session.execute(delete(IngestionRun).where(IngestionRun.id == ingestion_id))
                session.commit()
        engine.dispose()
