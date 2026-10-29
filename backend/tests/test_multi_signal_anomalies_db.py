"""Optional persistence check restricted to the isolated synthetic demo database."""

import os
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from backend.db.migrations import run_migrations
from backend.db.models import BehavioralAlertReview, IngestionRun, Transaction
from backend.services.multi_signal_anomalies import MultiSignalAnomalyService


def test_frequency_review_survives_service_recreation():
    url = os.getenv("FG_DEMO_DATABASE_URL")
    if not url:
        pytest.skip("Set FG_DEMO_DATABASE_URL for isolated PostgreSQL persistence check.")
    if not url.rsplit("/", 1)[-1].startswith("finance_guardian_demo"):
        pytest.fail("FG_DEMO_DATABASE_URL must target the isolated demo database.")
    engine = create_engine(url)
    tag = uuid4().hex[:12]
    run_id = None
    transaction_ids = []
    alert_id = None
    first = date(2026, 1, 5)
    as_of = first + timedelta(weeks=9)
    start_date = first + timedelta(weeks=8)
    try:
        run_migrations(engine)
        with Session(engine) as session:
            run = IngestionRun(source="test", filename="synthetic-behavioral",
                               source_fingerprint=f"behavioral-{tag}", status="completed")
            session.add(run)
            session.flush()
            run_id = run.id
            for week in range(9):
                for n in range(8 if week == 8 else 2):
                    transaction = Transaction(
                        ingestion_run_id=run_id, source="test",
                        source_transaction_key=f"behavioral-{tag}-{week}-{n}",
                        posted_date=first + timedelta(weeks=week, days=n % 7),
                        description=f"Synthetic cafe {tag}", merchant_name=f"Synthetic cafe {tag}",
                        amount=Decimal("10.00"), direction="debit", account_name="Synthetic",
                        iso_currency_code="USD", is_pending=False, status="active")
                    session.add(transaction)
                    session.flush()
                    transaction_ids.append(transaction.id)
            session.commit()
            service = MultiSignalAnomalyService(session)
            alerts = service.list_alerts(as_of, start_date)["alerts"]
            frequency = [item for item in alerts if item["signal_type"] == "frequency"
                         and item["entity_type"] == "merchant" and tag in item["entity_id"]]
            assert len(frequency) == 1
            alert_id = frequency[0]["alert_id"]
            service.review(alert_id, "unexpected", as_of, start_date, "USD")
        with Session(engine) as session:
            assert session.get(BehavioralAlertReview, alert_id).decision == "unexpected"
            service = MultiSignalAnomalyService(session)
            assert next(item for item in service.list_alerts(as_of, start_date)["alerts"]
                        if item["alert_id"] == alert_id)["review"] == "unexpected"
            service.review(alert_id, "unreviewed", as_of, start_date, "USD")
            assert session.get(BehavioralAlertReview, alert_id) is None
    finally:
        with Session(engine) as session:
            if alert_id:
                session.execute(delete(BehavioralAlertReview).where(BehavioralAlertReview.alert_id == alert_id))
            if transaction_ids:
                session.execute(delete(Transaction).where(Transaction.id.in_(transaction_ids)))
            if run_id:
                session.execute(delete(IngestionRun).where(IngestionRun.id == run_id))
            session.commit()
        engine.dispose()
