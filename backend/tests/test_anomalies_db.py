"""Persistence check uses only synthetic charges in the isolated demo database."""

import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from backend.db.migrations import run_migrations
from backend.db.models import AnomalyReview, IngestionRun, Transaction
from backend.services.anomalies import AnomalyService


def test_review_expected_unexpected_and_undo():
    url = os.getenv("FG_DEMO_DATABASE_URL")
    if not url:
        pytest.skip("Set FG_DEMO_DATABASE_URL for isolated PostgreSQL persistence check.")
    if not url.rsplit("/", 1)[-1].startswith("finance_guardian_demo"):
        pytest.fail("FG_DEMO_DATABASE_URL must target the isolated demo database.")
    engine = create_engine(url)
    tag = uuid4().hex[:12]
    run_id = None
    transaction_ids = []
    try:
        run_migrations(engine)
        with Session(engine) as session:
            run = IngestionRun(source="test", filename="synthetic-anomaly",
                               source_fingerprint=f"anomaly-{tag}", status="completed")
            session.add(run)
            session.flush()
            run_id = run.id
            for index in range(6):
                transaction = Transaction(
                    ingestion_run_id=run_id, source="test", source_transaction_key=f"anomaly-{tag}-{index}",
                    posted_date=date(2026, 10, index + 1), description=f"Synthetic merchant {tag}",
                    merchant_name=f"Synthetic merchant {tag}",
                    amount=Decimal("100.00" if index == 5 else "10.00"),
                    direction="debit", account_name="Synthetic", iso_currency_code="USD",
                    is_pending=False, status="active",
                )
                session.add(transaction)
                session.flush()
                transaction_ids.append(transaction.id)
            session.commit()
            service = AnomalyService(session)
            alerts = service.list_alerts(date(2026, 10, 27), date(2026, 10, 1))["alerts"]
            assert any(item["transaction_id"] == transaction_ids[-1] for item in alerts)
            service.review(transaction_ids[-1], "expected", date(2026, 10, 1), date(2026, 10, 27), "USD")
            assert session.get(AnomalyReview, transaction_ids[-1]).decision == "expected"
            service.review(transaction_ids[-1], "unexpected", date(2026, 10, 1), date(2026, 10, 27), "USD")
            assert session.get(AnomalyReview, transaction_ids[-1]).decision == "unexpected"
            service.review(transaction_ids[-1], "unreviewed", date(2026, 10, 1), date(2026, 10, 27), "USD")
            assert session.get(AnomalyReview, transaction_ids[-1]) is None
    finally:
        with Session(engine) as session:
            if transaction_ids:
                session.execute(delete(AnomalyReview).where(AnomalyReview.transaction_id.in_(transaction_ids)))
                session.execute(delete(Transaction).where(Transaction.id.in_(transaction_ids)))
            if run_id:
                session.execute(delete(IngestionRun).where(IngestionRun.id == run_id))
            session.commit()
        engine.dispose()
