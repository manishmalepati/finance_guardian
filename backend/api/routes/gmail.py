from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.common.exceptions import GmailIntegrationError
from backend.receipts.gmail_auth import GmailAuth
from backend.receipts.gmail_sync import GmailSync
from backend.receipts.models import EmailSource, GmailConnection, GmailSyncRun, Order, OrderItem, TransactionOrderMatch

router = APIRouter()


def require_local_app_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in {"http://localhost:3000", "http://localhost:3100"}:
        raise HTTPException(status_code=403, detail="Gmail actions require the local application.")


class DisconnectRequest(BaseModel):
    delete_extracted: bool = False


@router.get("/status")
def status(session: Session = Depends(get_session)) -> list[dict]:
    connections = session.scalars(select(GmailConnection).order_by(GmailConnection.created_at.desc())).all()
    return [{
        "id": connection.id, "email_address": connection.email_address,
        "status": connection.status, "last_sync_at": connection.last_sync_at,
        "source_count": session.scalar(select(func.count()).select_from(EmailSource).where(EmailSource.connection_id == connection.id)),
        "last_run": _last_run(session, connection.id),
    } for connection in connections]


def _last_run(session: Session, connection_id: str) -> dict | None:
    run = session.scalar(select(GmailSyncRun).where(
        GmailSyncRun.connection_id == connection_id
    ).order_by(GmailSyncRun.started_at.desc()).limit(1))
    if run is None:
        return None
    return {
        "status": run.status, "discovered": run.discovered_count,
        "imported": run.imported_count, "skipped": run.skipped_count,
        "failed": run.failed_count, "completed_at": run.completed_at,
    }


@router.post("/connect", dependencies=[Depends(require_local_app_origin)])
def connect(session: Session = Depends(get_session)) -> dict:
    with httpx.Client(timeout=20) as client:
        return GmailAuth(session, client).begin()


@router.get("/callback")
def callback(code: str = "", state: str = "", session: Session = Depends(get_session)):
    if not code or not state:
        return RedirectResponse("http://localhost:3000/?gmail=cancelled#accounts", status_code=303)
    try:
        with httpx.Client(timeout=20) as client:
            GmailAuth(session, client).complete(code, state)
    except GmailIntegrationError:
        return RedirectResponse("http://localhost:3000/?gmail=failed#accounts", status_code=303)
    return RedirectResponse("http://localhost:3000/?gmail=connected#accounts", status_code=303)


@router.post("/sync", dependencies=[Depends(require_local_app_origin)])
def sync(session: Session = Depends(get_session)) -> dict:
    connection = session.scalar(select(GmailConnection).where(GmailConnection.status == "active"))
    if connection is None:
        raise HTTPException(status_code=409, detail="Connect Gmail before syncing receipts.")
    with httpx.Client(timeout=20) as client:
        return GmailSync(session, client).sync(connection)


@router.post("/{connection_id}/disconnect", dependencies=[Depends(require_local_app_origin)])
def disconnect(connection_id: UUID, payload: DisconnectRequest, session: Session = Depends(get_session)) -> dict:
    connection = session.get(GmailConnection, str(connection_id))
    if connection is None:
        raise HTTPException(status_code=404, detail="Gmail connection was not found.")
    with httpx.Client(timeout=20) as client:
        revoked = GmailAuth(session, client).disconnect(connection)
    if payload.delete_extracted:
        source_ids = list(session.scalars(select(EmailSource.id).where(EmailSource.connection_id == connection.id)).all())
        if source_ids:
            order_ids = list(session.scalars(select(Order.id).where(Order.email_source_id.in_(source_ids))).all())
            if order_ids:
                session.execute(delete(TransactionOrderMatch).where(TransactionOrderMatch.order_id.in_(order_ids)))
                session.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
                session.execute(delete(Order).where(Order.id.in_(order_ids)))
            session.execute(delete(EmailSource).where(EmailSource.id.in_(source_ids)))
        session.execute(delete(GmailSyncRun).where(GmailSyncRun.connection_id == connection.id))
        session.delete(connection)
        session.commit()
    return {"disconnected": True, "google_revoked": revoked, "extracted_deleted": payload.delete_extracted}
