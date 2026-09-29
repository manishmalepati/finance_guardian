from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.agents.graph import FinanceAgent
from backend.common.exceptions import AgentExecutionError
from backend.core.config import settings
from backend.db.session import get_session
from backend.llm.providers import LLMProviderFactory

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
def chat(request: ChatRequest, session: Session = Depends(get_session)) -> dict:
    """Run the configured LLM-backed finance agent."""

    settings.require_agent_configuration()

    llm_provider = LLMProviderFactory(settings).build()
    try:
        result = FinanceAgent(session, llm_provider=llm_provider).invoke(request.message)
    except AgentExecutionError:
        raise
    except Exception as exc:
        raise AgentExecutionError() from exc
    return {
        "answer": result["answer"],
        "selected_tool": result["selected_tool"],
        "tool_result": result["tool_result"],
    }
