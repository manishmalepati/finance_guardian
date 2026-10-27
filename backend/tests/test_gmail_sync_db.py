"""Optional PostgreSQL integration check against the isolated demo database."""

import os
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from backend.db.models import Transaction
from backend.receipts.context import confirm_match, transaction_context, unlink_match
from backend.receipts.demo import uber_demo_message
from backend.receipts.gmail_auth import GmailAuth
from backend.receipts.gmail_sync import GmailSync, GMAIL_MESSAGES_URL
from backend.receipts.models import (
    EmailSource, GmailConnection, GmailSyncRun, Order, OrderItem, TransactionOrderMatch,
)
from backend.receipts.reconciliation import ReceiptReconciler


class FixtureResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FixtureGmailClient:
    def __init__(self, good_id: str, bad_id: str):
        self.good_id = good_id
        self.bad_id = bad_id

    def get(self, url, headers, params):
        assert headers["Authorization"] == "Bearer synthetic-test-token"
        if url == GMAIL_MESSAGES_URL:
            assert params["q"].startswith("from:noreply@uber.com")
            return FixtureResponse({"messages": [{"id": self.good_id}, {"id": self.bad_id}]})
        if url.endswith(self.good_id):
            return FixtureResponse(deepcopy(uber_demo_message()))
        if url.endswith(self.bad_id):
            broken = deepcopy(uber_demo_message())
            broken["payload"]["body"]["data"] = ""
            return FixtureResponse(broken)
        raise AssertionError("Unexpected Gmail request")


def test_repeat_sync_and_bad_message_recovery_in_demo_database(monkeypatch):
    url = os.getenv("FG_DEMO_DATABASE_URL")
    if not url:
        pytest.skip("Set FG_DEMO_DATABASE_URL to run the PostgreSQL Gmail integration check.")
    if not url.rsplit("/", 1)[-1].startswith("finance_guardian_demo"):
        pytest.fail("FG_DEMO_DATABASE_URL must target the isolated demo database.")

    engine = create_engine(url)
    unique = uuid4().hex
    good_id, bad_id = f"test-good-{unique}", f"test-bad-{unique}"
    monkeypatch.setattr(GmailAuth, "access_token", lambda self, connection: "synthetic-test-token")
    connection_id = None
    try:
        with Session(engine) as session:
            connection = GmailConnection(
                email_address=f"sync-{unique}@example.invalid",
                encrypted_refresh_token="synthetic-only",
                status="active",
            )
            session.add(connection)
            session.commit()
            connection_id = connection.id
            sync = GmailSync(session, FixtureGmailClient(good_id, bad_id))
            first = sync.sync(connection)
            assert (first["discovered"], first["imported"], first["failed"]) == (2, 1, 1)
            assert first["status"] == "completed_with_errors"

            second = sync.sync(connection)
            assert (second["discovered"], second["imported"], second["skipped"], second["failed"]) == (2, 0, 1, 1)
            sources = session.scalars(select(EmailSource).where(EmailSource.connection_id == connection_id)).all()
            assert {source.gmail_message_id: source.parse_status for source in sources} == {
                good_id: "complete", bad_id: "failed",
            }
            assert session.scalar(select(func.count()).select_from(Order).where(
                Order.email_source_id.in_([source.id for source in sources])
            )) == 1
            imported_order = session.scalar(select(Order).where(Order.email_source_id == next(
                source.id for source in sources if source.gmail_message_id == good_id
            )))
            transaction = session.scalar(select(Transaction).where(Transaction.description == "UBER EATS DEMO"))
            original = session.scalar(select(TransactionOrderMatch).where(
                TransactionOrderMatch.transaction_id == transaction.id,
                TransactionOrderMatch.order_id != imported_order.id,
            ))
            original_order_id = original.order_id
            assert original.status == "suggested"
            confirm_match(session, transaction.id, imported_order.id)
            linked = {match["order"]["id"] for match in transaction_context(session, transaction.id)["matches"]}
            assert linked == {original_order_id, imported_order.id}
            temporary_match = session.scalar(select(TransactionOrderMatch).where(
                TransactionOrderMatch.transaction_id == transaction.id,
                TransactionOrderMatch.order_id == imported_order.id,
            ))
            unlink_match(session, transaction.id, temporary_match.id)
            linked = {match["order"]["id"] for match in transaction_context(session, transaction.id)["matches"]}
            assert linked == {original_order_id}
    finally:
        if connection_id:
            with Session(engine) as session:
                source_ids = list(session.scalars(select(EmailSource.id).where(
                    EmailSource.connection_id == connection_id
                )))
                if source_ids:
                    order_ids = list(session.scalars(select(Order.id).where(Order.email_source_id.in_(source_ids))))
                    if order_ids:
                        session.execute(delete(TransactionOrderMatch).where(TransactionOrderMatch.order_id.in_(order_ids)))
                        session.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
                        session.execute(delete(Order).where(Order.id.in_(order_ids)))
                    session.execute(delete(EmailSource).where(EmailSource.id.in_(source_ids)))
                session.execute(delete(GmailSyncRun).where(GmailSyncRun.connection_id == connection_id))
                session.execute(delete(GmailConnection).where(GmailConnection.id == connection_id))
                ReceiptReconciler(session).reconcile_all()
                session.commit()
        engine.dispose()
