from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.services.plaid import PlaidService

router = APIRouter()


class ExchangePublicTokenRequest(BaseModel):
    public_token: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None


class SyncTransactionsRequest(BaseModel):
    item_id: str | None = None


@router.post("/link-token")
def create_link_token(session: Session = Depends(get_session)) -> dict:
    return PlaidService(session).create_link_token()


@router.post("/exchange-public-token")
def exchange_public_token(payload: ExchangePublicTokenRequest, session: Session = Depends(get_session)) -> dict:
    return PlaidService(session).exchange_public_token(payload.public_token, payload.metadata)


@router.post("/sync-transactions")
def sync_transactions(payload: SyncTransactionsRequest | None = None, session: Session = Depends(get_session)) -> dict:
    return PlaidService(session).sync_transactions(item_id=payload.item_id if payload else None)


@router.get("/items")
def list_items(session: Session = Depends(get_session)) -> list[dict]:
    return PlaidService(session).list_items()
