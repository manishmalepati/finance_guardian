"""Shared gross settled-purchase population for intelligence features."""

from collections import defaultdict
from datetime import date

from backend.domain.money_flow import MOVEMENT_CATEGORY_IDS


def eligible_purchases(rows: list[dict], as_of: date) -> tuple[list[dict], dict[str, int]]:
    """Keep posted debits and pair exact statement/Plaid overlap by occurrence.

    Credits, including possible refunds, are not netted without reconciliation.
    The caller must still scope currency and account for each analysis.
    """
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
