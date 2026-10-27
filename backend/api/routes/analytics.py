from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.services.analytics import AnalyticsService
from backend.services.spending_explanation import SpendingExplanationService

router = APIRouter()


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
