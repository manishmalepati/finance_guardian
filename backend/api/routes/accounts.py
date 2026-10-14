from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.services.accounts import AccountService

router = APIRouter()


@router.get("")
def list_accounts(session: Session = Depends(get_session)) -> list[dict]:
    return AccountService(session).list_accounts()
