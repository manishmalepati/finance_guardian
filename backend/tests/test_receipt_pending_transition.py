from decimal import Decimal
from types import SimpleNamespace

from backend.receipts.models import TransactionOrderMatch
from backend.services.plaid import PlaidService


class MatchSession:
    def __init__(self, source_match, target_match=None):
        self.source_match = source_match
        self.target_match = target_match
        self.added = []

    def scalars(self, statement):
        return SimpleNamespace(all=lambda: [self.source_match])

    def scalar(self, statement):
        return self.target_match

    def add(self, match):
        self.added.append(match)


def test_receipt_follows_pending_charge_when_posted_charge_replaces_it():
    original = TransactionOrderMatch(
        transaction_id="pending", order_id="order",
        status="confirmed", confidence=Decimal("0.970"),
        reasons=["exact total"], user_override=True,
    )
    session = MatchSession(original)
    PlaidService(session)._copy_receipt_matches(
        SimpleNamespace(id="pending"), SimpleNamespace(id="posted"),
    )
    assert original.status == "superseded"
    assert len(session.added) == 1
    moved = session.added[0]
    assert moved.transaction_id == "posted"
    assert moved.order_id == "order"
    assert moved.status == "confirmed"
    assert moved.user_override is True
    assert "moved from pending transaction" in moved.reasons
