"""Completed-period behavioral alerts; scores are signal-specific, never probabilities."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import BehavioralAlertReview
from backend.domain.transaction_eligibility import eligible_purchases
from backend.services.anomalies import AnomalyService, score_purchases
from backend.services.recurrence import detect_candidates


VERSION = "behavioral_v1"


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _id(signal: str, account: str | None, currency: str, entity: str, period: date) -> str:
    return sha256(f"{VERSION}|{signal}|{account or ''}|{currency}|{entity}|{period}".encode()).hexdigest()


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _alert(signal: str, entity_type: str, entity_id: str, account: str | None,
           currency: str, start: date, end: date, observed: str, baseline: str,
           references: list[str], explanation: str, **details) -> dict:
    return {"alert_id": _id(signal, account, currency, entity_id, start),
            "signal_type": signal, "entity_type": entity_type, "entity_id": entity_id,
            "account_id": account, "currency": currency,
            "period_start": start.isoformat(), "period_end": end.isoformat(),
            "observed_value": observed, "baseline_value": baseline,
            "supporting_transaction_ids": references[:20], "explanation": explanation,
            "method": VERSION, "review": "unreviewed", **details}


def _frequency(rows: list[dict], start_date: date, last_completed: date, currency: str) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        merchant = " ".join((row.get("normalized_merchant") or row["merchant"]).casefold().split())
        for kind, entity in (("merchant", merchant), ("category", row["category_id"] or "uncategorized")):
            if entity:
                groups[(kind, row["account_id"], entity)].append(row)
    alerts = []
    for (kind, account, entity), events in groups.items():
        first = _week_start(min(row["posted_date"] for row in events))
        counts = defaultdict(list)
        for row in events:
            counts[_week_start(row["posted_date"])].append(row)
        week = first + timedelta(weeks=8)
        while week <= last_completed:
            history = [len(counts[week - timedelta(weeks=offset)]) for offset in range(8, 0, -1)]
            active = sum(value > 0 for value in history)
            current = counts[week]
            if active >= 4 and len(current) >= 4:
                typical = Decimal(median(history))
                mad = Decimal(median([abs(Decimal(value) - typical) for value in history]))
                threshold = typical + max(Decimal(3), mad * Decimal("3"))
                if Decimal(len(current)) >= threshold and Decimal(len(current)) >= max(Decimal(2), typical * 2):
                    if week + timedelta(days=6) >= start_date:
                        alerts.append(_alert("frequency", kind, entity, account, currency,
                            week, week + timedelta(days=6), str(len(current)), str(typical),
                            [row["id"] for row in current],
                            f"{len(current)} purchases this completed week versus a median of {typical} over 8 earlier completed weeks.",
                            reference_weeks=8, active_reference_weeks=active,
                            historical_counts=history))
            week += timedelta(weeks=1)
    # If one merchant accounts for the entire category burst, present one alert.
    merchant_sets = {(item["account_id"], item["period_start"],
                      frozenset(item["supporting_transaction_ids"]))
                     for item in alerts if item["entity_type"] == "merchant"}
    return [item for item in alerts if item["entity_type"] == "merchant" or
            (item["account_id"], item["period_start"],
             frozenset(item["supporting_transaction_ids"])) not in merchant_sets]


def _drift(rows: list[dict], start_date: date, last_completed: date, currency: str) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[(row["account_id"], row["category_id"] or "uncategorized")].append(row)
    alerts = []
    for (account, category), events in groups.items():
        first = _week_start(min(row["posted_date"] for row in events))
        weeks = defaultdict(list)
        for row in events:
            weeks[_week_start(row["posted_date"])].append(row)
        week = first + timedelta(weeks=11)
        while week <= last_completed:
            prior = [sum((row["amount"] for row in weeks[week - timedelta(weeks=offset)]), Decimal(0))
                     for offset in range(11, 3, -1)]
            recent_periods = [week - timedelta(weeks=offset) for offset in (2, 1, 0)]
            recent = [sum((row["amount"] for row in weeks[period]), Decimal(0)) for period in recent_periods]
            typical = Decimal(median(prior))
            if typical > 0 and sum(value > 0 for value in prior) >= 5:
                high = all(value >= typical * Decimal("1.25") and value - typical >= Decimal("10")
                           for value in recent)
                previous = week - timedelta(weeks=3)
                previous_total = sum((row["amount"] for row in weeks[previous]), Decimal(0))
                if high and previous_total < typical * Decimal("1.25") and week + timedelta(days=6) >= start_date:
                    observed = sum(recent, Decimal(0)) / 3
                    prior_count = sum(len(weeks[week - timedelta(weeks=offset)]) for offset in range(11, 3, -1))
                    recent_rows = [row for period in recent_periods for row in weeks[period]]
                    recent_count = len(recent_rows)
                    driver = "frequency" if Decimal(recent_count) / 3 > Decimal(prior_count) / 8 * Decimal("1.25") else "average amount"
                    alerts.append(_alert("drift", "category", category, account, currency,
                        recent_periods[0], week + timedelta(days=6), _money(observed), _money(typical),
                        [row["id"] for row in recent_rows],
                        f"Average weekly spending rose from {_money(typical)} to {_money(observed)} {currency} for 3 completed weeks; the change is mainly {driver} driven.",
                        reference_weeks=8, sustained_weeks=3, driver=driver))
            week += timedelta(weeks=1)
    return alerts


def detect_signals(rows: list[dict], as_of: date, start_date: date, currency: str,
                   account_id: str | None = None, recurring_reviews: dict[str, str] | None = None) -> dict:
    purchases, excluded = eligible_purchases(rows, as_of)
    purchases = [row for row in purchases if row["currency"] == currency and
                 (account_id is None or row["account_id"] == account_id)]
    last_completed = _week_start(as_of) - timedelta(weeks=1)
    alerts = []
    amount_result = score_purchases(purchases, as_of, start_date, currency, account_id)
    for item in amount_result["alerts"]:
        day = date.fromisoformat(item["posted_date"])
        alerts.append(_alert("amount", "transaction", item["transaction_id"], item["account_id"],
            currency, day, day, item["amount"], item["typical_amount"],
            [item["transaction_id"], *item["reference_transaction_ids"]], item["reason"],
            merchant=item["merchant"], reference_kind=item["reference_kind"],
            reference_count=item["reference_count"], score=item["score"]))
    if last_completed >= start_date:
        alerts += _frequency(purchases, start_date, last_completed, currency)
        alerts += _drift(purchases, start_date, last_completed, currency)
    recurring = detect_candidates(purchases, as_of)["candidates"]
    amount_transaction_ids = {item["entity_id"] for item in alerts if item["signal_type"] == "amount"}
    for candidate in recurring:
        day = date.fromisoformat(candidate["last_date"])
        increase = candidate["latest_increase_vs_previous"]
        if day < start_date or not increase or candidate["transaction_ids"][-1] in amount_transaction_ids \
                or (recurring_reviews or {}).get(candidate["series_key"]) == "not_recurring":
            continue
        previous = Decimal(candidate["typical_amount"])
        latest = previous + Decimal(increase)
        if previous <= 0 or Decimal(increase) / previous < Decimal("0.10"):
            continue
        alerts.append(_alert("recurring_price", "recurring_series", candidate["series_key"],
            candidate["account_id"], currency, day, day, _money(latest), _money(previous),
            candidate["transaction_ids"],
            f"Latest {candidate['cadence']} payment is {_money(Decimal(increase))} {currency} above earlier typical payments; this series is a candidate, not a verified subscription.",
            merchant=candidate["merchant"], cadence=candidate["cadence"],
            recurring_review=(recurring_reviews or {}).get(candidate["series_key"], "unreviewed")))
    alerts.sort(key=lambda item: (item["period_end"], item["signal_type"], item["alert_id"]), reverse=True)
    return {"as_of": as_of.isoformat(), "start_date": start_date.isoformat(),
            "currency": currency, "account_id": account_id, "method": VERSION,
            "metric": "gross_settled_purchase_debits", "eligible_purchase_count": len(purchases),
            "excluded_counts": excluded, "alert_count": len(alerts), "alerts": alerts,
            "limitations": ["Posted-date backfills and historical category changes cannot be reconstructed exactly.",
                            "Signal scores are not probabilities or comparable across alert types."]}


class MultiSignalAnomalyService:
    def __init__(self, session: Session):
        self.session = session

    def list_alerts(self, as_of: date, start_date: date, currency: str = "USD",
                    account_id: str | None = None) -> dict:
        from backend.db.models import RecurringReview
        rows = AnomalyService(self.session).purchase_rows(as_of, start_date, account_id)
        recurring_reviews = {row.series_key: row.decision for row in self.session.scalars(select(RecurringReview))}
        result = detect_signals(rows, as_of, start_date, currency, account_id, recurring_reviews)
        ids = [item["alert_id"] for item in result["alerts"]]
        reviews = {row.alert_id: row.decision for row in self.session.scalars(
            select(BehavioralAlertReview).where(BehavioralAlertReview.alert_id.in_(ids)))} if ids else {}
        for item in result["alerts"]:
            item["review"] = reviews.get(item["alert_id"], "unreviewed")
        result["reviewed_alert_count"] = sum(item["review"] != "unreviewed" for item in result["alerts"])
        return result

    def review(self, alert_id: str, decision: str, as_of: date, start_date: date,
               currency: str, account_id: str | None = None) -> dict:
        if alert_id not in {item["alert_id"] for item in self.list_alerts(as_of, start_date, currency, account_id)["alerts"]}:
            raise LookupError("Behavioral alert not found")
        existing = self.session.get(BehavioralAlertReview, alert_id)
        if decision == "unreviewed":
            if existing:
                self.session.delete(existing)
        elif existing:
            existing.decision = decision
        else:
            self.session.add(BehavioralAlertReview(alert_id=alert_id, decision=decision))
        self.session.commit()
        return {"alert_id": alert_id, "review": decision}
