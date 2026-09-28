from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.services.ingestion import IngestionService

router = APIRouter()


@router.post("/chase-pdf")
async def import_chase_pdf(file: UploadFile = File(...), session: Session = Depends(get_session)) -> dict:
    content = await file.read()
    return IngestionService(session).import_statement(file.filename or "statement.pdf", content)
