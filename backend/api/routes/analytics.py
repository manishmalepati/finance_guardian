from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.services.analytics import AnalyticsService

router = APIRouter()


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
