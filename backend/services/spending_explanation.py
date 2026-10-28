"""Deterministic, posted-purchase spending attribution.

The comparison deliberately measures gross debits. Credits are shown as exclusions
until a refund can be linked to a purchase; no inferred refund is silently netted.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from backend.db.models import CategoryTaxonomy, Transaction, TransactionCategorization
from backend.domain.money_flow import MOVEMENT_CATEGORY_IDS


CENT = Decimal("0.01")


def _money(value: Decimal) -> str:
    return str(value.quantize(CENT))


def _group(rows: list[dict], key, label) -> list[dict]:
    buckets: dict[str, dict] = {}
    for row in rows:
        group_id = key(row)
        bucket = buckets.setdefault(group_id, {"id": group_id, "name": label(row),
                                                "prior": [], "current": []})
        bucket[row["period"]].append(row)

    output = []
    for bucket in buckets.values():
        prior, current = bucket["prior"], bucket["current"]
        prior_total = sum((row["amount"] for row in prior), Decimal(0))
        current_total = sum((row["amount"] for row in current), Decimal(0))
        delta = current_total - prior_total
        if prior and current:
            prior_average = prior_total / len(prior)
            frequency = (Decimal(len(current) - len(prior)) * prior_average).quantize(
                CENT, rounding=ROUND_HALF_EVEN)
            amount_effect = delta - frequency
            change_kind = "continuing"
        else:
            frequency, amount_effect = delta, Decimal(0)
            change_kind = "new" if current else "vanished"
        output.append({
            "id": bucket["id"], "name": bucket["name"],
            "prior_total": _money(prior_total), "current_total": _money(current_total),
            "delta": _money(delta), "prior_count": len(prior), "current_count": len(current),
            "prior_average": _money(prior_total / len(prior)) if prior else None,
            "current_average": _money(current_total / len(current)) if current else None,
            "frequency_effect": _money(frequency), "average_amount_effect": _money(amount_effect),
            "change_kind": change_kind,
            "prior_transaction_ids": [row["id"] for row in prior],
            "current_transaction_ids": [row["id"] for row in current],
        })
    return sorted(output, key=lambda item: (-abs(Decimal(item["delta"])), item["name"], item["id"]))


def explain_rows(rows: list[dict], *, prior_start: date, prior_end: date,
                 current_start: date, current_end: date, currency: str,
                 account_id: str | None = None) -> dict:
    """Pure attribution over canonical rows; useful for synthetic edge-case tests."""
    excluded = defaultdict(int)
    candidates = []
    for row in rows:
        if not (prior_start <= row["posted_date"] <= prior_end or
                current_start <= row["posted_date"] <= current_end):
            continue
        if row["status"] != "active" or row["is_pending"] or row.get("removed_at") \
                or row.get("replaced_by_transaction_id"):
            excluded["not_posted_active"] += 1
        elif row["currency"] != currency:
            excluded["other_or_missing_currency"] += 1
        elif row["direction"] == "credit":
            excluded["credits_including_refunds"] += 1
        elif row["movement_category_id"] in MOVEMENT_CATEGORY_IDS:
            excluded["transfers_and_card_payments"] += 1
        else:
            candidates.append(row)

    # Canonical IDs are unique, and source keys are unique inside each source.
    # For a statement/Plaid overlap, pair exact same-account/date/amount/merchant
    # occurrences by ordinal. Legitimate repeated purchases beyond the pair remain.
    def signature(row):
        return (row["account_id"], row["posted_date"], row["amount"],
                row["direction"], row["currency"], row["merchant"].casefold().strip())

    plaid_counts = defaultdict(int)
    for row in candidates:
        if row["source"] == "plaid":
            plaid_counts[signature(row)] += 1
    seen_statement = defaultdict(int)
    eligible = []
    seen_ids = set()
    for row in candidates:
        if row["id"] in seen_ids:
            excluded["duplicate_canonical_id"] += 1
            continue
        seen_ids.add(row["id"])
        if row["source"] == "statement":
            sig = signature(row)
            seen_statement[sig] += 1
            if seen_statement[sig] <= plaid_counts[sig]:
                excluded["exact_statement_plaid_overlap"] += 1
                continue
        eligible.append({**row, "period": "prior" if prior_start <= row["posted_date"] <= prior_end else "current"})
    prior = [row for row in eligible if row["period"] == "prior"]
    current = [row for row in eligible if row["period"] == "current"]
    prior_total = sum((row["amount"] for row in prior), Decimal(0))
    current_total = sum((row["amount"] for row in current), Decimal(0))
    delta = current_total - prior_total
    categories = _group(eligible, lambda row: row["category_id"] or "other_uncategorized",
                        lambda row: row["category_name"] or "Uncategorized")
    merchants = _group(eligible, lambda row: f'{row["category_id"] or "other_uncategorized"}|{row["merchant"].casefold()}',
                       lambda row: row["merchant"])
    for merchant in merchants:
        merchant["category_id"] = merchant["id"].split("|", 1)[0]
    category_sum = sum((Decimal(row["delta"]) for row in categories), Decimal(0))
    merchant_sum = sum((Decimal(row["delta"]) for row in merchants), Decimal(0))
    if category_sum != delta or merchant_sum != delta:
        raise ArithmeticError("Spending contributions did not reconcile")
    return {
        "prior_period": {"start": prior_start.isoformat(), "end": prior_end.isoformat(),
                         "days": (prior_end - prior_start).days + 1},
        "current_period": {"start": current_start.isoformat(), "end": current_end.isoformat(),
                           "days": (current_end - current_start).days + 1},
        "comparable_length": (prior_end - prior_start) == (current_end - current_start),
        "currency": currency, "account_id": account_id,
        "prior_total": _money(prior_total), "current_total": _money(current_total),
        "delta": _money(delta), "prior_count": len(prior), "current_count": len(current),
        "categories": categories, "merchants": merchants,
        "reconciliation_difference": _money(delta - category_sum),
        "excluded_counts": dict(excluded),
        "metric": "gross_posted_purchase_debits",
        "refund_policy": "Credits, including possible refunds, are excluded until explicitly linked to a purchase.",
    }


class SpendingExplanationService:
    def __init__(self, session: Session):
        self.session = session

    def compare(self, prior_start: date, prior_end: date, current_start: date,
                current_end: date, currency: str = "USD", account_id: str | None = None) -> dict:
        ranked = select(
            TransactionCategorization.transaction_id.label("transaction_id"),
            TransactionCategorization.category_id.label("category_id"),
            TransactionCategorization.canonical_merchant_name.label("canonical_merchant_name"),
            func.row_number().over(
                partition_by=TransactionCategorization.transaction_id,
                order_by=(TransactionCategorization.updated_at.desc(), TransactionCategorization.id.desc()),
            ).label("rank"),
        ).where(TransactionCategorization.status == "active").subquery()
        parent = aliased(CategoryTaxonomy)
        statement = (select(
            Transaction.id, Transaction.account_id, Transaction.posted_date, Transaction.amount,
            Transaction.direction, Transaction.status, Transaction.is_pending,
            Transaction.removed_at, Transaction.replaced_by_transaction_id,
            Transaction.iso_currency_code, Transaction.source,
            ranked.c.category_id, ranked.c.canonical_merchant_name,
            CategoryTaxonomy.display_name.label("subcategory_name"),
            parent.category_id.label("parent_id"), parent.display_name.label("parent_name"),
            Transaction.merchant_name, Transaction.description,
        ).select_from(Transaction).outerjoin(
            ranked, and_(ranked.c.transaction_id == Transaction.id, ranked.c.rank == 1)
        ).outerjoin(CategoryTaxonomy, CategoryTaxonomy.category_id == ranked.c.category_id
        ).outerjoin(parent, parent.category_id == CategoryTaxonomy.parent_category_id
        ).where(
            ((Transaction.posted_date >= prior_start) & (Transaction.posted_date <= prior_end)) |
            ((Transaction.posted_date >= current_start) & (Transaction.posted_date <= current_end))
        ))
        if account_id:
            statement = statement.where(Transaction.account_id == account_id)
        rows = []
        for item in self.session.execute(statement).mappings():
            category_id = item["category_id"]
            rows.append({
                "id": str(item["id"]), "account_id": str(item["account_id"]) if item["account_id"] else None,
                "posted_date": item["posted_date"], "amount": item["amount"],
                "direction": item["direction"], "status": item["status"],
                "is_pending": item["is_pending"], "removed_at": item["removed_at"],
                "replaced_by_transaction_id": item["replaced_by_transaction_id"],
                "currency": item["iso_currency_code"], "source": item["source"],
                "movement_category_id": category_id,
                "category_id": item["parent_id"] or category_id,
                "category_name": item["parent_name"] or item["subcategory_name"] or "Uncategorized",
                "merchant": (item["canonical_merchant_name"] or item["merchant_name"] or item["description"]).strip(),
            })
        return explain_rows(rows, prior_start=prior_start, prior_end=prior_end,
                            current_start=current_start, current_end=current_end,
                            currency=currency, account_id=account_id)
