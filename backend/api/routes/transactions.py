from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.repositories.transactions import TransactionRepository

router = APIRouter()


@router.get("")
def list_transactions(
    limit: int = Query(default=100, ge=1, le=500),
    start_date: date | None = None,
    end_date: date | None = None,
    query: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict]:
    rows = TransactionRepository(session).list_transactions(
        limit=limit, start_date=start_date, end_date=end_date, query=query
    )
    return [
        {
            "id": row.id,
            "posted_date": row.posted_date.isoformat(),
            "description": row.description,
            "amount": row.amount,
            "direction": row.direction,
            "account_name": row.account_name,
            "category_hint": row.category_hint,
        }
        for row in rows
    ]
