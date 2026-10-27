from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.receipts.context import confirm_match, correct_item, search_orders, unlink_match

router = APIRouter()


class ItemCorrection(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=500)
    category_id: str | None = Field(default=None, max_length=50)


@router.get("/orders")
def list_orders(query: str = Query(default="", max_length=120), session: Session = Depends(get_session)) -> list[dict]:
    return search_orders(session, query)


@router.patch("/items/{item_id}")
def update_item(item_id: UUID, payload: ItemCorrection, session: Session = Depends(get_session)) -> dict:
    return correct_item(session, str(item_id), payload.description, payload.category_id)
