"""Conservative month-end gross purchase forecasts with walk-forward evaluation."""

import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import CategoryTaxonomy, Goal
from backend.domain.transaction_eligibility import eligible_purchases
from backend.services.anomalies import AnomalyService
from backend.services.recurrence import RecurrenceService


VERSION = "month_end_baselines_v1"


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _month(day: date) -> tuple[int, int]:
    return day.year, day.month


def _days(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def _observed(rows: list[dict], cutoff: date) -> Decimal:
    return sum((row["amount"] for row in rows if _month(row["posted_date"]) == _month(cutoff)
                and row["posted_date"] <= cutoff), Decimal(0))


def _history(rows: list[dict], cutoff: date) -> list[Decimal]:
    totals = defaultdict(lambda: Decimal(0))
    for row in rows:
        if _month(row["posted_date"]) < _month(cutoff):
            totals[_month(row["posted_date"])] += row["amount"]
    if not totals:
        return []
    first = min(totals)
    months = []
    year, month = first
    while (year, month) < _month(cutoff):
        months.append(totals[(year, month)])
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _candidates(rows: list[dict], cutoff: date) -> tuple[dict[str, Decimal], int, Decimal]:
    observed = _observed(rows, cutoff)
    run_rate = observed * Decimal(_days(cutoff)) / Decimal(cutoff.day)
    history = _history(rows, cutoff)
    result = {"daily_run_rate": max(observed, run_rate)}
    if len(history) >= 3:
        result["historical_monthly_median"] = max(observed, Decimal(median(history[-12:])))
    return result, len(history), observed


def backtest_rows(rows: list[dict], as_of: date) -> dict:
    """Idealized posted-date backtest; never uses later posted transactions as features."""
    all_months = []
    if rows:
        year, month = min(_month(row["posted_date"]) for row in rows)
        while (year, month) < _month(as_of):
            all_months.append((year, month))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    errors: dict[str, list[Decimal]] = defaultdict(list)
    actuals: dict[str, list[Decimal]] = defaultdict(list)
    by_day: dict[int, dict[str, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
    calibration: dict[str, list[Decimal]] = defaultdict(list)
    intervals: dict[str, list[tuple[bool, Decimal]]] = defaultdict(list)
    case_errors: dict[str, dict[tuple[int, int, int], Decimal]] = defaultdict(dict)
    for year, month in all_months:
        month_end = date(year, month, calendar.monthrange(year, month)[1])
        actual = _observed(rows, month_end)
        month_errors: dict[str, list[Decimal]] = defaultdict(list)
        for day in (7, 15, 22):
            if day >= month_end.day:
                continue
            cutoff = date(year, month, day)
            visible = [row for row in rows if row["posted_date"] <= cutoff]
            predictions, _, observed = _candidates(visible, cutoff)
            for method, prediction in predictions.items():
                error = abs(prediction - actual)
                older_errors = sorted(calibration[method])
                if len(older_errors) >= 6:
                    margin = older_errors[min(len(older_errors) - 1, int(0.8 * len(older_errors)))]
                    lower = max(observed, prediction - margin)
                    upper = prediction + margin
                    intervals[method].append((lower <= actual <= upper, upper - lower))
                errors[method].append(error)
                case_errors[method][(year, month, day)] = error
                month_errors[method].append(error)
                actuals[method].append(actual)
                by_day[day][method].append(error)
        for method, values in month_errors.items():
            calibration[method].extend(values)
    metrics = {}
    shared_cases = set.intersection(*(set(cases) for cases in case_errors.values())) if case_errors else set()
    for method, values in errors.items():
        denominator = sum(actuals[method], Decimal(0))
        metrics[method] = {"cases": len(values),
                           "mae": _money(sum(values, Decimal(0)) / len(values)),
                           "wape": round(float(sum(values, Decimal(0)) / denominator), 3) if denominator else None,
                           "interval_cases": len(intervals[method]),
                           "interval_coverage": round(sum(covered for covered, _ in intervals[method]) / len(intervals[method]), 3) if intervals[method] else None,
                           "mean_interval_width": _money(sum((width for _, width in intervals[method]), Decimal(0)) / len(intervals[method])) if intervals[method] else None,
                           "comparison_cases": len(shared_cases),
                           "comparison_mae": _money(sum((case_errors[method][case] for case in shared_cases), Decimal(0)) / len(shared_cases)) if shared_cases else None,
                           "error_by_cutoff_day": {str(day): _money(sum(day_errors[method], Decimal(0)) / len(day_errors[method]))
                                                   for day, day_errors in by_day.items() if day_errors[method]}}
    return {"metrics": metrics, "absolute_errors": errors,
            "historical_cutoff_policy": "posted_date_only_current_categorization"}


def forecast_rows(rows: list[dict], as_of: date, currency: str = "USD",
                  account_id: str | None = None, category_id: str | None = None,
                  category_ids: set[str] | None = None, budget: Decimal | None = None) -> dict:
    purchases, excluded = eligible_purchases(rows, as_of)
    scoped = [row for row in purchases if row["currency"] == currency
              and (account_id is None or row["account_id"] == account_id)
              and (category_id is None or row["category_id"] in (category_ids or {category_id}))]
    historical_totals = _history(scoped, as_of) if scoped else []
    sporadic = (len(historical_totals) >= 3 and
                sum(value > 0 for value in historical_totals) * 2 < len(historical_totals)
                and _observed(scoped, as_of) == 0)
    if not scoped or sporadic:
        return {"as_of": as_of.isoformat(), "month": f"{as_of.year:04d}-{as_of.month:02d}",
                "currency": currency, "account_id": account_id, "category_id": category_id,
                "metric": "gross_settled_purchase_debits", "method": "insufficient_data",
                "version": VERSION, "confidence": "insufficient_data", "observed_to_date": "0.00",
                "forecast_remaining": None, "forecast_total": None, "lower_bound": None,
                "upper_bound": None, "historical_complete_months": len(historical_totals),
                "eligible_purchase_count": len(scoped), "excluded_counts": excluded,
                "budget": _money(budget) if budget is not None else None,
                "budget_status": "insufficient_data" if budget is not None else None,
                "forecast_overshoot": None,
                "backtest": {"metrics": backtest_rows(scoped, as_of)["metrics"] if sporadic else {}},
                "limitations": ["Sporadic historical spending without current purchases cannot support a useful month-end estimate."
                                if sporadic else "No eligible purchase history exists for this scope."]}
    predictions, history_count, observed = _candidates(scoped, as_of)
    evaluation = backtest_rows(scoped, as_of)
    metrics = evaluation["metrics"]
    eligible_methods = [method for method in predictions if metrics.get(method, {}).get("cases", 0) >= 6]
    if eligible_methods:
        chosen = min(eligible_methods, key=lambda method: (
            Decimal(metrics[method]["comparison_mae"] or metrics[method]["mae"]), method))
        confidence = "evaluated"
    elif "historical_monthly_median" in predictions:
        chosen, confidence = "historical_monthly_median", "provisional"
    else:
        chosen, confidence = "daily_run_rate", "provisional"
    estimate = predictions[chosen]
    errors = sorted(evaluation["absolute_errors"].get(chosen, []))
    lower = upper = None
    if len(errors) >= 6:
        margin = errors[min(len(errors) - 1, int(0.8 * len(errors)))]
        lower = max(observed, estimate - margin)
        upper = estimate + margin
    status = None
    if budget is not None:
        status = "already_over_budget" if observed > budget else (
            "projected_over_budget" if estimate > budget else "currently_within_budget")
    return {"as_of": as_of.isoformat(), "month": f"{as_of.year:04d}-{as_of.month:02d}",
            "currency": currency, "account_id": account_id, "category_id": category_id,
            "metric": "gross_settled_purchase_debits", "method": chosen,
            "version": VERSION, "confidence": confidence,
            "observed_to_date": _money(observed),
            "forecast_remaining": _money(max(Decimal(0), estimate - observed)),
            "forecast_total": _money(estimate),
            "lower_bound": _money(lower) if lower is not None else None,
            "upper_bound": _money(upper) if upper is not None else None,
            "historical_complete_months": history_count,
            "eligible_purchase_count": len(scoped), "excluded_counts": excluded,
            "budget": _money(budget) if budget is not None else None,
            "budget_status": status,
            "forecast_overshoot": _money(max(Decimal(0), estimate - budget)) if budget is not None else None,
            "backtest": {"metrics": metrics, "historical_cutoff_policy": evaluation["historical_cutoff_policy"]},
            "limitations": ["Historical ingestion and category state at each cutoff cannot be reconstructed.",
                            "Bounds use empirical backtest errors, not calibrated probabilities."]}


class ForecastService:
    def __init__(self, session: Session):
        self.session = session

    def forecast(self, as_of: date, currency: str = "USD", account_id: str | None = None,
                 category_id: str | None = None) -> dict:
        rows = AnomalyService(self.session).purchase_rows(as_of, as_of, account_id)
        category_ids = None
        if category_id:
            category_ids = {category_id}
            category_ids.update(item.category_id for item in self.session.scalars(
                select(CategoryTaxonomy).where(CategoryTaxonomy.parent_category_id == category_id)))
        goal = self.session.scalar(select(Goal).where(Goal.metric_type == "monthly_spend",
                                                  Goal.status == "active", Goal.category_id == category_id,
                                                  Goal.currency == currency)) if category_id else None
        result = forecast_rows(rows, as_of, currency, account_id, category_id,
                               category_ids, goal.threshold_amount if goal else None)
        if category_id is None:
            categories = sorted({row["category_id"] for row in rows if row["category_id"]})
            result["category_breakdown"] = [
                {"category_id": item, **{key: value for key, value in forecast_rows(
                    rows, as_of, currency, account_id, item).items()
                    if key in ("observed_to_date", "forecast_total", "confidence", "method")}}
                for item in categories
            ]
            month_end = date(as_of.year, as_of.month, _days(as_of))
            recurring = RecurrenceService(self.session).list_candidates(as_of, account_id)["candidates"]
            result["confirmed_upcoming_recurring"] = [
                {"series_key": item["series_key"], "merchant": item["merchant"],
                 "next_expected_date": item["next_expected_date"], "typical_amount": item["typical_amount"],
                 "currency": item["currency"], "transaction_ids": item["transaction_ids"][-3:]}
                for item in recurring if item.get("review") == "confirmed" and item["currency"] == currency
                and as_of < date.fromisoformat(item["next_expected_date"]) <= month_end
            ]
            result["recurring_policy"] = "Confirmed upcoming charges are shown separately and not added to a forecast that may already include them."
        return result
