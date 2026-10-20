"""Goal rules. New metrics and scopes register here without changing API plumbing."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from backend.db.models import Goal, Transaction


@dataclass(frozen=True)
class EvidenceRow:
    transaction: Transaction
    category_id: str | None
    parent_category_id: str | None


class ScopeRule(Protocol):
    def includes(self, target_id: str, row: EvidenceRow) -> bool: ...


class CategoryScope:
    def includes(self, target_id: str, row: EvidenceRow) -> bool:
        return row.parent_category_id == target_id or row.category_id == target_id or (
            target_id == "other" and row.category_id is None
        )


class SubcategoryScope:
    def includes(self, target_id: str, row: EvidenceRow) -> bool:
        return row.category_id == target_id


SCOPES: dict[str, ScopeRule] = {"category": CategoryScope(), "subcategory": SubcategoryScope()}


def month_bounds(month: str | None, timezone: str, now: datetime | None = None) -> tuple[date, date]:
    local_today = (now or datetime.now(UTC)).astimezone(ZoneInfo(timezone)).date()
    first = date.fromisoformat(f"{month}-01") if month else local_today.replace(day=1)
    next_first = date(first.year + 1, 1, 1) if first.month == 12 else date(first.year, first.month + 1, 1)
    return first, next_first - timedelta(days=1)


class GoalMetric(Protocol):
    def evaluate(self, goal: Goal, rows: list[EvidenceRow], month: str | None = None,
                 now: datetime | None = None) -> dict: ...


class MonthlySpendMetric:
    """Posted scoped debits minus scoped credits; pending is projected only."""

    def evaluate(self, goal: Goal, rows: list[EvidenceRow], month: str | None = None,
                 now: datetime | None = None) -> dict:
        first, last = month_bounds(month, goal.timezone, now)
        scope = SCOPES[goal.scope_kind]
        gross = credits = pending_debits = pending_credits = Decimal("0.00")
        unknown_currency = other_currency = 0
        evidence = []
        for row in rows:
            tx = row.transaction
            if not first <= tx.posted_date <= last or not scope.includes(goal.category_id, row):
                continue
            if not tx.iso_currency_code or tx.iso_currency_code != goal.currency:
                unknown_currency += int(not tx.iso_currency_code)
                other_currency += int(bool(tx.iso_currency_code))
                continue
            pending = tx.is_pending or tx.status == "pending"
            if pending:
                if tx.direction == "debit":
                    pending_debits += tx.amount
                else:
                    pending_credits += tx.amount
            elif tx.direction == "debit":
                gross += tx.amount
            else:
                credits += tx.amount
            evidence.append({
                "transaction_id": tx.id, "posted_date": tx.posted_date.isoformat(),
                "merchant": tx.merchant_name or tx.description,
                "amount": tx.amount, "direction": tx.direction,
                "pending": pending, "category_id": row.category_id,
            })
        posted = max(Decimal("0.00"), gross - credits)
        pending_net = pending_debits - pending_credits
        projected = max(Decimal("0.00"), gross - credits + pending_net)
        threshold = goal.threshold_amount
        caveats = ["Pending transactions are shown as projected exposure and do not count toward posted progress."]
        if credits:
            caveats.append("Credits in this scope reduce net spend; a credit is not independently verified as a refund.")
        if unknown_currency:
            caveats.append("Transactions with unknown currency were excluded.")
        if other_currency:
            caveats.append("Transactions in a different currency were excluded; no conversion was assumed.")
        return {
            "goal_id": goal.id, "month": first.strftime("%Y-%m"),
            "period_start": first.isoformat(), "period_end": last.isoformat(),
            "evaluated_at": (now or datetime.now(UTC)).isoformat(),
            "threshold_amount": threshold, "currency": goal.currency,
            "posted_gross": gross, "posted_credits": credits,
            "posted_spend": posted, "pending_net": pending_net,
            "projected_spend": projected,
            "remaining": max(Decimal("0.00"), threshold - posted),
            "over_amount": max(Decimal("0.00"), posted - threshold),
            "progress_percent": (posted / threshold * 100).quantize(Decimal("0.1")),
            "evidence": evidence,
            "exclusions": {"unknown_currency": unknown_currency, "other_currency": other_currency},
            "caveats": caveats,
        }


METRICS: dict[str, GoalMetric] = {"monthly_spend": MonthlySpendMetric()}
