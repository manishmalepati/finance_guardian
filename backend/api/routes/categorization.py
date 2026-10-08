from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.common.exceptions import AgentExecutionError
from backend.db.session import get_session
from backend.services.categorization import CategorizationService

router = APIRouter()


class TransactionCategoryUpdate(BaseModel):
    category_id: str = Field(min_length=1)
    canonical_merchant_name: str | None = None
    apply_to_matching_merchant: bool = True


@router.get("/categories")
def list_categories(session: Session = Depends(get_session)) -> list[dict]:
    return CategorizationService(session).list_categories()


@router.get("/jobs")
def list_jobs(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict]:
    return CategorizationService(session).list_jobs(limit=limit, status=status)


@router.get("/summary")
def summary(session: Session = Depends(get_session)) -> dict:
    return CategorizationService(session).summary()


@router.post("/apply-known")
def apply_known_aliases(session: Session = Depends(get_session)) -> dict:
    return CategorizationService(session).apply_known_aliases_and_queue_unknowns()


@router.post("/categorize-unknowns")
def categorize_unknowns(
    limit: int = Query(default=8, ge=1, le=25),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return CategorizationService(session).categorize_with_llm(limit=limit)
    except AgentExecutionError:
        raise


@router.patch("/transactions/{transaction_id}")
def update_transaction_category(
    transaction_id: str,
    request: TransactionCategoryUpdate,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return CategorizationService(session).set_transaction_category(
            transaction_id=transaction_id,
            category_id=request.category_id,
            canonical_merchant_name=request.canonical_merchant_name,
            apply_to_matching_merchant=request.apply_to_matching_merchant,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
