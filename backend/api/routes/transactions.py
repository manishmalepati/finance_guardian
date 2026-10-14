from datetime import date
from uuid import UUID

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
    account_id: UUID | None = None,
    category_id: str | None = None,
    merchant: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict]:
    rows = TransactionRepository(session).list_transaction_details(
        limit=limit, start_date=start_date, end_date=end_date, query=query,
        account_id=str(account_id) if account_id else None, category_id=category_id, merchant=merchant,
    )
    output = []
    for transaction, categorization, category, parent_category in rows:
        output.append(
            {
                "id": transaction.id,
                "posted_date": transaction.posted_date.isoformat(),
                "description": transaction.description,
                "amount": transaction.amount,
                "direction": transaction.direction,
                "status": transaction.status,
                "is_pending": transaction.is_pending,
                "account_name": transaction.account_name,
                "account_id": transaction.account_id,
                "category_hint": transaction.category_hint,
                "plaid_pfc_primary": transaction.plaid_pfc_primary,
                "plaid_pfc_detailed": transaction.plaid_pfc_detailed,
                "plaid_pfc_confidence": transaction.plaid_pfc_confidence,
                "category_id": categorization.category_id if categorization else None,
                "category_name": parent_category.display_name if parent_category else "Uncategorized",
                "parent_category_id": parent_category.category_id if parent_category else None,
                "parent_category_name": parent_category.display_name if parent_category else "Uncategorized",
                "subcategory_id": category.category_id if category else None,
                "subcategory_name": category.display_name if category else None,
                "canonical_merchant_name": categorization.canonical_merchant_name if categorization else None,
                "categorization_source": categorization.source if categorization else None,
                "categorization_confidence": categorization.confidence if categorization else None,
            }
        )
    return output
