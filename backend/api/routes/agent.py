from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.agents.graph import FinanceAgent
from backend.core.config import settings
from backend.db.session import get_session

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
def chat(request: ChatRequest, session: Session = Depends(get_session)) -> dict:
    configuration_error = settings.agent_configuration_error()
    if configuration_error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=configuration_error,
        )

    result = FinanceAgent(session).invoke(request.message)
    return {
        "answer": result["answer"],
        "selected_tool": result["selected_tool"],
        "tool_result": result["tool_result"],
    }
