from datetime import date
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.services.analytics import AnalyticsService
from backend.services.spending_explanation import SpendingExplanationService
from backend.services.recurrence import RecurrenceService
from backend.services.anomalies import AnomalyService

router = APIRouter()


@router.get("/anomalies")
def anomalies(
    start_date: date, end_date: date, currency: str = "USD",
    account_id: UUID | None = None, session: Session = Depends(get_session),
) -> dict:
    if end_date < start_date or end_date > date.today() or (end_date - start_date).days > 365:
        raise HTTPException(status_code=400, detail="Choose a past date range of at most 366 days.")
    currency = currency.upper()
    if len(currency) != 3 or not currency.isalpha():
        raise HTTPException(status_code=400, detail="Currency must be a three-letter ISO code.")
    return AnomalyService(session).list_alerts(end_date, start_date, currency,
                                               str(account_id) if account_id else None)


class AnomalyReviewSelection(BaseModel):
    decision: Literal["expected", "unexpected", "unreviewed"]
    start_date: date
    end_date: date
    currency: str = "USD"
    account_id: UUID | None = None


@router.put("/anomalies/{transaction_id}/review")
def review_anomaly(transaction_id: UUID, payload: AnomalyReviewSelection,
                   session: Session = Depends(get_session)) -> dict:
    if payload.end_date < payload.start_date or payload.end_date > date.today() \
            or (payload.end_date - payload.start_date).days > 365:
        raise HTTPException(status_code=400, detail="Choose a past date range of at most 366 days.")
    currency = payload.currency.upper()
    if len(currency) != 3 or not currency.isalpha():
        raise HTTPException(status_code=400, detail="Currency must be a three-letter ISO code.")
    try:
        return AnomalyService(session).review(str(transaction_id), payload.decision,
                                             payload.start_date, payload.end_date, currency,
                                             str(payload.account_id) if payload.account_id else None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/recurring-charges")
def recurring_charges(
    as_of: date | None = None,
    account_id: UUID | None = None,
    session: Session = Depends(get_session),
) -> dict:
    as_of = as_of or date.today()
    if as_of > date.today():
        raise HTTPException(status_code=400, detail="As-of date cannot be in the future.")
    return RecurrenceService(session).list_candidates(as_of, str(account_id) if account_id else None)


class RecurringReviewSelection(BaseModel):
    decision: Literal["confirmed", "not_recurring", "unreviewed"]
    as_of: date


@router.put("/recurring-charges/{series_key}/review")
def review_recurring_charge(
    series_key: str,
    payload: RecurringReviewSelection,
    session: Session = Depends(get_session),
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", series_key):
        raise HTTPException(status_code=400, detail="Invalid recurring series key.")
    if payload.as_of > date.today():
        raise HTTPException(status_code=400, detail="As-of date cannot be in the future.")
    try:
        return RecurrenceService(session).review(series_key, payload.decision, payload.as_of)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/explain-spending")
def explain_spending(
    prior_start: date,
    prior_end: date,
    current_start: date,
    current_end: date,
    currency: str = "USD",
    account_id: UUID | None = None,
    session: Session = Depends(get_session),
) -> dict:
    if prior_end < prior_start or current_end < current_start:
        raise HTTPException(status_code=400, detail="Each period must end on or after it starts.")
    if prior_end >= current_start:
        raise HTTPException(status_code=400, detail="Periods must be chronological and must not overlap.")
    if (prior_end - prior_start).days > 365 or (current_end - current_start).days > 365:
        raise HTTPException(status_code=400, detail="Each period must be 366 days or shorter.")
    currency = currency.upper()
    if len(currency) != 3 or not currency.isalpha():
        raise HTTPException(status_code=400, detail="Currency must be a three-letter ISO code.")
    return SpendingExplanationService(session).compare(
        prior_start, prior_end, current_start, current_end, currency,
        str(account_id) if account_id else None,
    )


@router.get("/spending-report")
def spending_report(
    start_date: date,
    end_date: date,
    account_id: UUID | None = None,
    session: Session = Depends(get_session),
) -> dict:
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="End date must be on or after start date.")
    return AnalyticsService(session).spending_report(start_date, end_date, str(account_id) if account_id else None)


@router.get("/monthly-summary")
def monthly_summary(session: Session = Depends(get_session)) -> list[dict]:
    return AnalyticsService(session).monthly_summary()


@router.get("/category-spending")
def category_spending(
    start_date: date | None = None,
    end_date: date | None = None,
    session: Session = Depends(get_session),
) -> list[dict]:
    return AnalyticsService(session).category_spending(start_date=start_date, end_date=end_date)


@router.get("/largest-transactions")
def largest_transactions(limit: int = 10, session: Session = Depends(get_session)) -> list[dict]:
    return AnalyticsService(session).largest_transactions(limit=limit)
