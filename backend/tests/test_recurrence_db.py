"""Persistence check using only synthetic records in the isolated demo database."""

import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from backend.db.models import IngestionRun, RecurringReview, Transaction
from backend.services.recurrence import RecurrenceService


def test_review_confirm_dismiss_and_undo_persist():
    url = os.getenv("FG_DEMO_DATABASE_URL")
    if not url:
        pytest.skip("Set FG_DEMO_DATABASE_URL for the isolated PostgreSQL review check.")
    if not url.rsplit("/", 1)[-1].startswith("finance_guardian_demo"):
        pytest.fail("FG_DEMO_DATABASE_URL must target the isolated demo database.")
    engine = create_engine(url)
    tag = uuid4().hex[:12]
    key = None
    run_id = None
    transaction_ids = []
    try:
        with Session(engine) as session:
            ingestion = IngestionRun(source="test", filename="synthetic-recurrence",
                                     source_fingerprint=f"recurrence-{tag}", status="completed")
            session.add(ingestion)
            session.flush()
            run_id = ingestion.id
            for index, day in enumerate((1, 8, 15)):
                transaction = Transaction(
                    ingestion_run_id=run_id, source="test", source_transaction_key=f"recurrence-{tag}-{index}",
                    posted_date=date(2026, 10, day), description="SYNTHETIC RECURRING TEST",
                    merchant_name=f"Synthetic service {tag}", amount=Decimal("12.00"),
                    direction="debit", account_name="Synthetic", iso_currency_code="USD",
                    is_pending=False, status="active",
                )
                session.add(transaction)
                session.flush()
                transaction_ids.append(transaction.id)
            session.commit()

            service = RecurrenceService(session)
            candidates = [item for item in service.list_candidates(date(2026, 10, 27))["candidates"]
                          if item["merchant"] == f"Synthetic service {tag}"]
            assert len(candidates) == 1
            key = candidates[0]["series_key"]
            assert candidates[0]["review"] == "unreviewed"
            service.review(key, "confirmed", date(2026, 10, 27))
            assert session.get(RecurringReview, key).decision == "confirmed"
            service.review(key, "not_recurring", date(2026, 10, 27))
            assert session.get(RecurringReview, key).decision == "not_recurring"
            service.review(key, "unreviewed", date(2026, 10, 27))
            assert session.get(RecurringReview, key) is None
    finally:
        with Session(engine) as session:
            if key:
                session.execute(delete(RecurringReview).where(RecurringReview.series_key == key))
            if transaction_ids:
                session.execute(delete(Transaction).where(Transaction.id.in_(transaction_ids)))
            if run_id:
                session.execute(delete(IngestionRun).where(IngestionRun.id == run_id))
            session.commit()
        engine.dispose()
