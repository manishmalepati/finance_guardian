"""Prior-only, explainable unusual-purchase ranking. Scores are not probabilities."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from backend.db.models import AnomalyReview, Transaction, TransactionCategorization
from backend.domain.money_flow import MOVEMENT_CATEGORY_IDS


def eligible_purchases(rows: list[dict], as_of: date) -> tuple[list[dict], dict[str, int]]:
    excluded = defaultdict(int)
    candidates = []
    seen = set()
    for row in rows:
        if row["posted_date"] > as_of or row["status"] != "active" or row["is_pending"] \
                or row.get("removed_at") or row.get("replaced_by_transaction_id"):
            excluded["not_settled_active"] += 1
        elif row["direction"] != "debit":
            excluded["credits_including_refunds"] += 1
        elif row["category_id"] in MOVEMENT_CATEGORY_IDS:
            excluded["transfers_and_card_payments"] += 1
        elif not row["currency"] or row["amount"] <= 0:
            excluded["missing_currency_or_nonpositive_amount"] += 1
        elif row["id"] in seen:
            excluded["duplicate_canonical_id"] += 1
        else:
            seen.add(row["id"])
            candidates.append(row)

    def signature(row: dict) -> tuple:
        return (row["account_id"], row["posted_date"], row["amount"], row["currency"],
                row["merchant"].casefold().strip())

    plaid = defaultdict(int)
    for row in candidates:
        if row["source"] == "plaid":
            plaid[signature(row)] += 1
    statement = defaultdict(int)
    eligible = []
    for row in candidates:
        if row["source"] == "statement":
            key = signature(row)
            statement[key] += 1
            if statement[key] <= plaid[key]:
                excluded["exact_statement_plaid_overlap"] += 1
                continue
        eligible.append(row)
    return sorted(eligible, key=lambda row: (row["posted_date"], row["id"])), dict(excluded)


def score_purchases(rows: list[dict], as_of: date, start_date: date, currency: str,
                    account_id: str | None = None) -> dict:
    """Compare each purchase only with earlier posted dates in its own currency/account."""
    purchases, excluded = eligible_purchases(rows, as_of)
    history = defaultdict(list)
    alerts = []
    for row in purchases:
        if row["currency"] != currency or (account_id and row["account_id"] != account_id):
            continue
        account = row["account_id"] or "unlinked"
        merchant = " ".join((row.get("normalized_merchant") or row["merchant"]).casefold().split())
        keys = [("merchant", account, currency, merchant),
                ("category", account, currency, row["category_id"] or "uncategorized"),
                ("account", account, currency, "all")]
        reference = None
        reference_kind = ""
        for kind, *parts in keys:
            earlier = [item for item in history[(kind, *parts)] if item["posted_date"] < row["posted_date"]]
            minimum = {"merchant": 5, "category": 12, "account": 20}[kind]
            if len(earlier) >= minimum:
                reference, reference_kind = earlier, kind
                break
        if reference and start_date <= row["posted_date"] <= as_of:
            amounts = [item["amount"] for item in reference]
            typical = Decimal(median(amounts))
            mad = Decimal(median([abs(amount - typical) for amount in amounts]))
            # A scale floor keeps uniform low-value series from producing infinite scores.
            scale = max(mad * Decimal("1.4826"), typical * Decimal("0.15"), Decimal("2.00"))
            excess = row["amount"] - typical
            score = excess / scale
            if typical > 0 and excess >= Decimal("10.00") and row["amount"] >= typical * Decimal("1.8") \
                    and score >= Decimal("3.5"):
                evidence = sorted(reference, key=lambda item: (item["posted_date"], item["id"]))[-5:]
                alerts.append({
                    "transaction_id": row["id"], "posted_date": row["posted_date"].isoformat(),
                    "merchant": row["merchant"], "account_id": row["account_id"],
                    "category_id": row["category_id"], "currency": currency,
                    "amount": str(row["amount"]), "typical_amount": str(typical.quantize(Decimal("0.01"))),
                    "amount_above_typical": str(excess.quantize(Decimal("0.01"))),
                    "score": round(float(score), 2), "reference_kind": reference_kind,
                    "reference_count": len(reference),
                    "reference_transaction_ids": [item["id"] for item in evidence],
                    "reason": f"This charge is above the earlier {reference_kind} median.",
                })
        for key in keys:
            history[key].append(row)
    alerts.sort(key=lambda item: (-item["score"], item["posted_date"], item["transaction_id"]))
    reviewed_count = sum(1 for item in alerts if item.get("review") in ("expected", "unexpected"))
    return {"as_of": as_of.isoformat(), "start_date": start_date.isoformat(),
            "currency": currency, "account_id": account_id, "eligible_purchase_count": len(purchases),
            "alert_count": len(alerts), "reviewed_alert_count": reviewed_count,
            "excluded_counts": excluded, "method": "prior_only_robust_amount_v1",
            "probability_claim": False, "alerts": alerts}


class AnomalyService:
    def __init__(self, session: Session):
        self.session = session

    def list_alerts(self, as_of: date, start_date: date, currency: str = "USD",
                    account_id: str | None = None) -> dict:
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
            Transaction.iso_currency_code, Transaction.source, Transaction.merchant_name,
            Transaction.description, ranked.c.category_id, ranked.c.normalized_merchant,
            ranked.c.canonical_merchant_name,
        ).select_from(Transaction).outerjoin(
            ranked, and_(ranked.c.transaction_id == Transaction.id, ranked.c.rank == 1)
        ).where(Transaction.posted_date >= start_date - timedelta(days=3 * 366),
                Transaction.posted_date <= as_of))
        if account_id:
            statement = statement.where(Transaction.account_id == account_id)
        rows = [{
            "id": str(item["id"]), "account_id": str(item["account_id"]) if item["account_id"] else None,
            "posted_date": item["posted_date"], "amount": item["amount"],
            "direction": item["direction"], "status": item["status"],
            "is_pending": item["is_pending"], "removed_at": item["removed_at"],
            "replaced_by_transaction_id": item["replaced_by_transaction_id"],
            "currency": item["iso_currency_code"], "source": item["source"],
            "category_id": item["category_id"],
            "merchant": (item["canonical_merchant_name"] or item["merchant_name"] or item["description"]).strip(),
            "normalized_merchant": item["normalized_merchant"],
        } for item in self.session.execute(statement).mappings()]
        result = score_purchases(rows, as_of, start_date, currency, account_id)
        ids = [item["transaction_id"] for item in result["alerts"]]
        reviews = {item.transaction_id: item.decision for item in self.session.scalars(
            select(AnomalyReview).where(AnomalyReview.transaction_id.in_(ids)))} if ids else {}
        for item in result["alerts"]:
            item["review"] = reviews.get(item["transaction_id"], "unreviewed")
        result["reviewed_alert_count"] = sum(item["review"] != "unreviewed" for item in result["alerts"])
        return result

    def review(self, transaction_id: str, decision: str, start_date: date, as_of: date,
               currency: str, account_id: str | None = None) -> dict:
        candidates = self.list_alerts(as_of, start_date, currency, account_id)["alerts"]
        if transaction_id not in {item["transaction_id"] for item in candidates}:
            raise LookupError("Unusual-charge candidate not found")
        existing = self.session.get(AnomalyReview, transaction_id)
        if decision == "unreviewed":
            if existing:
                self.session.delete(existing)
        elif existing:
            existing.decision = decision
        else:
            self.session.add(AnomalyReview(transaction_id=transaction_id, decision=decision))
        self.session.commit()
        return {"transaction_id": transaction_id, "review": decision}
