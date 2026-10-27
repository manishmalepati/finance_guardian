"""Conservative receipt-to-ledger matching. The ledger never includes orders."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Candidate:
    transaction_id: str
    amount: Decimal
    currency: str | None
    merchant: str
    authorized_date: date | None
    posted_date: date
    direction: str
    status: str


@dataclass(frozen=True)
class MatchEvidence:
    transaction_id: str
    confidence: Decimal
    reasons: list[str]


def _merchant_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def rank_candidates(order, candidates: list[Candidate]) -> list[MatchEvidence]:
    """Rank candidates; a score is evidence, not proof of a purchase."""
    ranked: list[MatchEvidence] = []
    for candidate in candidates:
        if candidate.direction != "debit" or candidate.status not in {"active", "pending"}:
            continue
        if order.currency is not None and candidate.currency is not None and order.currency != candidate.currency:
            continue
        same_currency = order.currency is not None and candidate.currency is not None
        reasons: list[str] = ["same currency" if same_currency else "currency unknown"]
        score = Decimal("0.100") if same_currency else Decimal("0")
        if order.total is not None and candidate.amount == order.total:
            score += Decimal("0.450")
            reasons.append("exact total")
        elif order.total is not None and abs(candidate.amount - order.total) <= Decimal("5.00"):
            score += Decimal("0.100")
            reasons.append("near total; fees or adjustment possible")
        else:
            continue
        if _merchant_key(order.merchant) in _merchant_key(candidate.merchant):
            score += Decimal("0.250")
            reasons.append("merchant agrees")
        order_date = order.placed_date or (order.placed_at.date() if order.placed_at else None)
        if order_date:
            distance = min(abs((value - order_date).days) for value in (candidate.authorized_date, candidate.posted_date) if value)
            if distance <= 1:
                score += Decimal("0.200")
                reasons.append("date within one day")
            elif distance <= 7:
                score += Decimal("0.100")
                reasons.append("date within seven days")
            else:
                continue
        ranked.append(MatchEvidence(candidate.transaction_id, min(score, Decimal("1.000")), reasons))
    return sorted(ranked, key=lambda value: (-value.confidence, value.transaction_id))


def automatic_match(order, candidates: list[Candidate]) -> MatchEvidence | None:
    ranked = rank_candidates(order, candidates)
    complete_currency = order.currency is not None and all(candidate.currency == order.currency for candidate in candidates)
    return ranked[0] if complete_currency and len(ranked) == 1 and ranked[0].confidence >= Decimal("1.000") else None
