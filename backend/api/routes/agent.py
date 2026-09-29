from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.agents.graph import FinanceAgent
from backend.core.config import settings
from backend.db.session import get_session
from backend.llm.providers import LLMProviderFactory

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
def chat(request: ChatRequest, session: Session = Depends(get_session)) -> dict:
    """Run the configured LLM-backed finance agent."""

    configuration_error = settings.agent_configuration_error()
    if configuration_error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=configuration_error,
        )

    llm_provider = LLMProviderFactory(settings).build()
    try:
        result = FinanceAgent(session, llm_provider=llm_provider).invoke(request.message)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agent execution failed. Check LLM credentials, model configuration, and logs.",
        ) from exc
    return {
        "answer": result["answer"],
        "selected_tool": result["selected_tool"],
        "tool_result": result["tool_result"],
    }
