"""Idempotent receipt matching after either source changes.

Bank transactions remain the ledger. This service only updates evidence links.
Callers own the transaction and commit after reconciliation succeeds.
"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.db.models import Transaction
from backend.receipts.matching import Candidate, automatic_match, rank_candidates
from backend.receipts.models import Order, TransactionOrderMatch


class ReceiptReconciler:
    def __init__(self, session: Session):
        self.session = session

    def reconcile_all(self) -> dict[str, int]:
        counts = {"orders_checked": 0, "links_created": 0, "links_updated": 0}
        for order in self.session.scalars(select(Order).where(
            Order.total.is_not(None),
            or_(Order.placed_date.is_not(None), Order.placed_at.is_not(None)),
        )).all():
            result = self.reconcile_order(order)
            counts["orders_checked"] += 1
            counts["links_created"] += result["created"]
            counts["links_updated"] += result["updated"]
        return counts

    def reconcile_order(self, order: Order) -> dict[str, int]:
        order_date = order.placed_date or (order.placed_at.date() if order.placed_at else None)
        if order_date is None or order.total is None:
            return {"created": 0, "updated": 0}

        transactions = self.session.scalars(select(Transaction).where(
            Transaction.posted_date >= order_date - timedelta(days=7),
            Transaction.posted_date <= order_date + timedelta(days=10),
            Transaction.status.in_(("active", "pending")),
            Transaction.direction == "debit",
        )).all()
        candidates = [Candidate(
            transaction_id=row.id, amount=row.amount, currency=row.iso_currency_code,
            merchant=row.merchant_name or row.description,
            authorized_date=row.authorized_date, posted_date=row.posted_date,
            direction=row.direction, status=row.status,
        ) for row in transactions]
        ranked = rank_candidates(order, candidates)
        strong = automatic_match(order, candidates) if order.parse_quality == "complete" else None
        existing = {match.transaction_id: match for match in self.session.scalars(
            select(TransactionOrderMatch).where(TransactionOrderMatch.order_id == order.id)
        ).all()}
        confirmed_order = any(match.status == "confirmed" and match.user_override for match in existing.values())
        if confirmed_order:
            strong = None
        if strong:
            strong_candidate = next(candidate for candidate in candidates if candidate.transaction_id == strong.transaction_id)
            nearby_orders = self.session.scalars(select(Order).where(
                Order.id != order.id,
                Order.total == order.total,
                Order.currency == order.currency,
                Order.parse_quality == "complete",
                Order.placed_date >= order_date - timedelta(days=2),
                Order.placed_date <= order_date + timedelta(days=2),
            )).all()
            if any(any(evidence.confidence == Decimal("1.000") for evidence in rank_candidates(
                other_order, [strong_candidate]
            )) for other_order in nearby_orders):
                strong = None
        if strong:
            other_confirmation = self.session.scalar(select(TransactionOrderMatch.id).where(
                TransactionOrderMatch.transaction_id == strong.transaction_id,
                TransactionOrderMatch.order_id != order.id,
                TransactionOrderMatch.status == "confirmed",
            ))
            if other_confirmation:
                strong = None

        desired = {evidence.transaction_id: evidence for evidence in ranked[:3]
                   if evidence.confidence >= Decimal("0.500")}
        created = updated = 0
        for transaction_id, match in existing.items():
            if match.user_override:
                continue
            evidence = desired.get(transaction_id)
            if evidence is None:
                if match.status in {"suggested", "confirmed"}:
                    match.status = "superseded"
                    updated += 1
                continue
            status = "confirmed" if strong and strong.transaction_id == transaction_id else "suggested"
            if match.status != status or match.confidence != evidence.confidence or match.reasons != evidence.reasons:
                match.status = status
                match.confidence = evidence.confidence
                match.reasons = evidence.reasons
                updated += 1

        for transaction_id, evidence in desired.items():
            if transaction_id in existing:
                continue
            self.session.add(TransactionOrderMatch(
                transaction_id=transaction_id, order_id=order.id,
                status="confirmed" if strong and strong.transaction_id == transaction_id else "suggested",
                confidence=evidence.confidence, reasons=evidence.reasons, user_override=False,
            ))
            created += 1
        self.session.flush()
        return {"created": created, "updated": updated}
