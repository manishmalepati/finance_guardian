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
    rows = TransactionRepository(session).list_transaction_details(
        limit=limit, start_date=start_date, end_date=end_date, query=query
    )
    output = []
    for transaction, categorization, category in rows:
        output.append(
            {
                "id": transaction.id,
                "posted_date": transaction.posted_date.isoformat(),
                "description": transaction.description,
                "amount": transaction.amount,
                "direction": transaction.direction,
                "account_name": transaction.account_name,
                "category_hint": transaction.category_hint,
                "category_id": categorization.category_id if categorization else None,
                "category_name": category.display_name if category else "Uncategorized",
                "canonical_merchant_name": categorization.canonical_merchant_name if categorization else None,
                "categorization_source": categorization.source if categorization else None,
                "categorization_confidence": categorization.confidence if categorization else None,
            }
        )
    return output
