"""Synthetic goal and budget integration against the isolated demo database."""

import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

from backend.api.routes.budgets import MonthlyLimitInput, list_monthly_limits, set_monthly_limit
from backend.db.models import (
    CategoryTaxonomy, Goal, IngestionRun, Transaction, TransactionCategorization,
)
from backend.db.migrations.goals_002 import upgrade as migrate_legacy_limits
from backend.goals.service import GoalConflict, GoalService


def test_goal_scope_evidence_pause_and_budget_facade():
    url = os.getenv("FG_DEMO_DATABASE_URL")
    if not url:
        pytest.skip("Set FG_DEMO_DATABASE_URL for the isolated PostgreSQL goal check.")
    if not url.rsplit("/", 1)[-1].startswith("finance_guardian_demo"):
        pytest.fail("FG_DEMO_DATABASE_URL must target the isolated demo database.")

    engine = create_engine(url)
    tag = uuid4().hex[:12]
    parent_id, child_id, sibling_id = f"test_parent_{tag}", f"test_child_{tag}", f"test_sibling_{tag}"
    ingestion_id = None
    goal_ids: list[str] = []
    transaction_ids: list[str] = []
    try:
        with Session(engine) as session:
            session.add_all([
                CategoryTaxonomy(category_id=parent_id, parent_category_id=None,
                                 display_name="Synthetic parent", level=1, sort_order=900, is_active=True),
                CategoryTaxonomy(category_id=child_id, parent_category_id=parent_id,
                                 display_name="Synthetic child", level=2, sort_order=901, is_active=True),
                CategoryTaxonomy(category_id=sibling_id, parent_category_id=parent_id,
                                 display_name="Synthetic sibling", level=2, sort_order=902, is_active=True),
            ])
            ingestion = IngestionRun(source="test", filename="synthetic-goal",
                                     source_fingerprint=f"goal-{tag}", status="completed")
            session.add(ingestion)
            session.commit()
            ingestion_id = ingestion.id

            def add_transaction(key: str, amount: str, category_id: str, *, direction="debit",
                                pending=False, currency="USD"):
                tx = Transaction(
                    ingestion_run_id=ingestion.id, source="test", source_transaction_key=f"{tag}-{key}",
                    posted_date=date(2026, 10, 15), description="SYNTHETIC GOAL TEST",
                    merchant_name="Synthetic", amount=Decimal(amount), direction=direction,
                    account_name="Synthetic", iso_currency_code=currency,
                    is_pending=pending, status="pending" if pending else "active",
                )
                session.add(tx)
                session.flush()
                transaction_ids.append(tx.id)
                session.add(TransactionCategorization(
                    transaction_id=tx.id, normalized_merchant="synthetic",
                    canonical_merchant_name="Synthetic", category_id=category_id,
                    source="test", status="active",
                ))

            add_transaction("child-debit", "70.00", child_id)
            add_transaction("child-credit", "10.00", child_id, direction="credit")
            add_transaction("sibling-pending", "30.00", sibling_id, pending=True)
            add_transaction("other-currency", "50.00", child_id, currency="EUR")
            session.commit()

            service = GoalService(session)
            parent = service.create(category_id=parent_id, threshold_amount=Decimal("100.00"), timezone="UTC")
            child = service.create(category_id=child_id, threshold_amount=Decimal("50.00"), timezone="UTC")
            goal_ids.extend((parent["id"], child["id"]))
            with pytest.raises(GoalConflict):
                service.create(category_id=child_id, threshold_amount=Decimal("20.00"), timezone="UTC")

            parent_result = service.evaluate(service.get(parent["id"]), "2026-10")
            child_result = service.evaluate(service.get(child["id"]), "2026-10")
            assert (parent_result["posted_spend"], parent_result["pending_net"]) == (
                Decimal("60.00"), Decimal("30.00"),
            )
            assert {item["transaction_id"] for item in parent_result["evidence"]} == set(transaction_ids[:3])
            assert parent_result["exclusions"]["other_currency"] == 1
            assert child_result["posted_spend"] == Decimal("60.00")
            assert child_result["over_amount"] == Decimal("10.00")

            changed = set_monthly_limit(parent_id, MonthlyLimitInput(amount=Decimal("120.00")), session)
            assert changed["amount"] == Decimal("120.00")
            assert service.find_monthly_scope(parent_id).id == parent["id"]
            service.update(child["id"], {"status": "paused"})
            active_limits = {row["category_id"] for row in list_monthly_limits(session)}
            assert parent_id in active_limits and child_id not in active_limits
            assert service.evaluate(service.get(child["id"]), "2026-10")["posted_spend"] == Decimal("60.00")
    finally:
        with Session(engine) as session:
            if goal_ids:
                session.execute(delete(Goal).where(Goal.id.in_(goal_ids)))
            if transaction_ids:
                session.execute(delete(TransactionCategorization).where(
                    TransactionCategorization.transaction_id.in_(transaction_ids)
                ))
                session.execute(delete(Transaction).where(Transaction.id.in_(transaction_ids)))
            if ingestion_id:
                session.execute(delete(IngestionRun).where(IngestionRun.id == ingestion_id))
            session.execute(delete(CategoryTaxonomy).where(
                CategoryTaxonomy.category_id.in_((child_id, sibling_id))
            ))
            session.execute(delete(CategoryTaxonomy).where(CategoryTaxonomy.category_id == parent_id))
            session.commit()
        engine.dispose()


def test_legacy_limit_migration_is_idempotent():
    url = os.getenv("FG_DEMO_DATABASE_URL")
    if not url:
        pytest.skip("Set FG_DEMO_DATABASE_URL for the isolated PostgreSQL goal check.")
    if not url.rsplit("/", 1)[-1].startswith("finance_guardian_demo"):
        pytest.fail("FG_DEMO_DATABASE_URL must target the isolated demo database.")

    engine = create_engine(url)
    category_id = f"test_legacy_{uuid4().hex[:12]}"
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("""insert into enrichment.category_taxonomy
                    (category_id, display_name, level, sort_order, is_active)
                    values (:id, 'Synthetic legacy category', 1, 999, true)
                """), {"id": category_id})
                connection.execute(text("""insert into planning.monthly_category_limits
                    (category_id, amount) values (:id, 125.00)
                """), {"id": category_id})
                migrate_legacy_limits(connection)
                migrate_legacy_limits(connection)
                rows = connection.execute(text("""select threshold_amount, scope_kind, currency
                    from planning.goals where category_id = :id
                """), {"id": category_id}).all()
                assert rows == [(Decimal("125.00"), "category", "USD")]
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
