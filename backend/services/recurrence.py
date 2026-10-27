"""Explainable recurring-charge candidates from settled purchase history."""

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from statistics import median

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from backend.db.models import RecurringReview, Transaction, TransactionCategorization
from backend.domain.money_flow import MOVEMENT_CATEGORY_IDS


CADENCES = (
    ("weekly", 7, 2),
    ("biweekly", 14, 2),
    ("monthly", 30, 3),
    ("yearly", 365, 14),
)


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _next_date(last: date, cadence: str, anchor_day: int) -> date:
    if cadence == "weekly":
        return last + timedelta(days=7)
    if cadence == "biweekly":
        return last + timedelta(days=14)
    if cadence == "yearly":
        year = last.year + 1
        return date(year, last.month, min(anchor_day, calendar.monthrange(year, last.month)[1]))
    year = last.year + (last.month // 12)
    month = last.month % 12 + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def detect_candidates(rows: list[dict], as_of: date) -> dict:
    """Pure detector. Review status is applied separately by the database service."""
    excluded = defaultdict(int)
    eligible = []
    seen_ids = set()
    for row in rows:
        if row["posted_date"] > as_of or row["status"] != "active" or row["is_pending"] \
                or row.get("removed_at") or row.get("replaced_by_transaction_id"):
            excluded["not_settled_active"] += 1
        elif row["direction"] != "debit":
            excluded["credits"] += 1
        elif row["category_id"] in MOVEMENT_CATEGORY_IDS:
            excluded["movements"] += 1
        elif not row["currency"]:
            excluded["missing_currency"] += 1
        elif row["id"] in seen_ids:
            excluded["duplicate_canonical_id"] += 1
        else:
            seen_ids.add(row["id"])
            eligible.append(row)

    # Pair only exact statement/Plaid representations of the same purchase.
    def signature(row):
        return (row["account_id"], row["posted_date"], row["amount"], row["currency"],
                row["merchant"].casefold().strip())

    plaid_counts = defaultdict(int)
    for row in eligible:
        if row["source"] == "plaid":
            plaid_counts[signature(row)] += 1
    statement_counts = defaultdict(int)
    purchases = []
    for row in eligible:
        if row["source"] == "statement":
            sig = signature(row)
            statement_counts[sig] += 1
            if statement_counts[sig] <= plaid_counts[sig]:
                excluded["exact_statement_plaid_overlap"] += 1
                continue
        purchases.append(row)

    groups = defaultdict(list)
    for row in purchases:
        merchant_key = " ".join((row.get("normalized_merchant") or row["merchant"]).casefold().split())
        groups[(row["account_id"] or "unlinked", row["currency"], merchant_key)].append(row)

    candidates = []
    for (account_id, currency, merchant_key), events in groups.items():
        events.sort(key=lambda event: (event["posted_date"], event["id"]))
        dates = sorted({event["posted_date"] for event in events})
        if len(dates) < 3 or not merchant_key:
            continue
        gaps = [(later - earlier).days for earlier, later in zip(dates, dates[1:])]
        fits = []
        for cadence, target, tolerance in CADENCES:
            matches = sum(abs(gap - target) <= tolerance for gap in gaps)
            if matches >= 2 and matches / len(gaps) >= 0.75:
                fit = Decimal(matches) / Decimal(len(gaps))
                error = sum(abs(gap - target) for gap in gaps if abs(gap - target) <= tolerance)
                fits.append((fit, -error, cadence, target, tolerance, matches))
        if not fits:
            continue
        _, _, cadence, target, tolerance, matches = max(fits)
        amounts = [event["amount"] for event in events]
        typical = Decimal(median(amounts))
        if typical <= 0:
            continue
        deviation = Decimal(median([abs(amount - typical) for amount in amounts])) / typical
        if deviation > Decimal("0.45"):
            continue
        anchor_day = int(median([day.day for day in dates]))
        if dates[-1].day >= 28 and sum(day.day >= 28 for day in dates) >= len(dates) - 1:
            anchor_day = max(day.day for day in dates)
        next_expected = _next_date(dates[-1], cadence, anchor_day)
        if as_of > next_expected + timedelta(days=target * 2):
            continue  # Old patterns should not masquerade as upcoming charges.
        confidence = ("high" if len(dates) >= 4 and matches == len(gaps) and deviation <= Decimal("0.10")
                      else "medium" if matches / len(gaps) >= 0.75 and deviation <= Decimal("0.25")
                      else "low")
        previous_typical = Decimal(median(amounts[:-1]))
        latest_increase = (amounts[-1] - previous_typical
                           if amounts[-1] > previous_typical * Decimal("1.10")
                           and amounts[-1] - previous_typical >= Decimal("1.00") else None)
        key = sha256(f"{account_id}|{currency}|{merchant_key}".encode()).hexdigest()
        candidates.append({
            "series_key": key, "merchant": events[-1]["merchant"],
            "account_id": None if account_id == "unlinked" else account_id,
            "currency": currency, "cadence": cadence, "confidence": confidence,
            "transaction_count": len(events), "distinct_dates": len(dates),
            "matching_intervals": matches, "observed_intervals": len(gaps),
            "typical_amount": _money(typical),
            "latest_increase_vs_previous": _money(latest_increase) if latest_increase else None,
            "observed_low": _money(min(amounts)), "observed_high": _money(max(amounts)),
            "last_date": dates[-1].isoformat(), "next_expected_date": next_expected.isoformat(),
            "timing": "overdue" if next_expected < as_of else "upcoming",
            "interval_tolerance_days": tolerance,
            "transaction_ids": [event["id"] for event in events],
            "reason": (f"{matches} of {len(gaps)} intervals are near {target} days "
                       f"(within {tolerance} days); observed amounts range from "
                       f"{_money(min(amounts))} to {_money(max(amounts))} {currency}."),
        })
    candidates.sort(key=lambda item: (item["next_expected_date"], item["merchant"], item["series_key"]))
    return {"as_of": as_of.isoformat(), "candidate_count": len(candidates),
            "eligible_purchase_count": len(purchases), "merchant_account_groups": len(groups),
            "excluded_counts": dict(excluded), "candidates": candidates,
            "method": "rules_v1", "probability_claim": False}


class RecurrenceService:
    def __init__(self, session: Session):
        self.session = session

    def list_candidates(self, as_of: date, account_id: str | None = None) -> dict:
        ranked = select(
            TransactionCategorization.transaction_id.label("transaction_id"),
            TransactionCategorization.category_id.label("category_id"),
            TransactionCategorization.normalized_merchant.label("normalized_merchant"),
            TransactionCategorization.canonical_merchant_name.label("canonical_merchant_name"),
            func.row_number().over(
                partition_by=TransactionCategorization.transaction_id,
                order_by=(TransactionCategorization.updated_at.desc(), TransactionCategorization.id.desc()),
            ).label("rank"),
        ).where(TransactionCategorization.status == "active").subquery()
        statement = (select(
            Transaction.id, Transaction.account_id, Transaction.posted_date, Transaction.amount,
            Transaction.direction, Transaction.status, Transaction.is_pending,
            Transaction.removed_at, Transaction.replaced_by_transaction_id,
            Transaction.iso_currency_code, Transaction.source,
            Transaction.merchant_name, Transaction.description,
            ranked.c.category_id, ranked.c.normalized_merchant, ranked.c.canonical_merchant_name,
        ).select_from(Transaction).outerjoin(
            ranked, and_(ranked.c.transaction_id == Transaction.id, ranked.c.rank == 1)
        ).where(Transaction.posted_date >= as_of - timedelta(days=3 * 366),
                Transaction.posted_date <= as_of))
        if account_id:
            statement = statement.where(Transaction.account_id == account_id)
        rows = []
        for item in self.session.execute(statement).mappings():
            rows.append({
                "id": str(item["id"]), "account_id": str(item["account_id"]) if item["account_id"] else None,
                "posted_date": item["posted_date"], "amount": item["amount"],
                "direction": item["direction"], "status": item["status"],
                "is_pending": item["is_pending"], "removed_at": item["removed_at"],
                "replaced_by_transaction_id": item["replaced_by_transaction_id"],
                "currency": item["iso_currency_code"], "source": item["source"],
                "category_id": item["category_id"],
                "merchant": (item["canonical_merchant_name"] or item["merchant_name"] or item["description"]).strip(),
                "normalized_merchant": item["normalized_merchant"],
            })
        result = detect_candidates(rows, as_of)
        keys = [item["series_key"] for item in result["candidates"]]
        reviews = {}
        if keys:
            reviews = {item.series_key: item.decision for item in self.session.scalars(
                select(RecurringReview).where(RecurringReview.series_key.in_(keys))
            )}
        for candidate in result["candidates"]:
            candidate["review"] = reviews.get(candidate["series_key"], "unreviewed")
        return result

    def review(self, series_key: str, decision: str, as_of: date) -> dict:
        candidates = self.list_candidates(as_of)["candidates"]
        if series_key not in {item["series_key"] for item in candidates}:
            raise LookupError("Recurring candidate not found")
        existing = self.session.get(RecurringReview, series_key)
        if decision == "unreviewed":
            if existing:
                self.session.delete(existing)
        elif existing:
            existing.decision = decision
        else:
            self.session.add(RecurringReview(series_key=series_key, decision=decision))
        self.session.commit()
        return {"series_key": series_key, "review": decision}
