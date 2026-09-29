from __future__ import annotations

import json
import re
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.agents.state import AgentState
from backend.llm.base import LLMProvider


class ToolPlan(BaseModel):
    """LLM-selected tool call for one finance question."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = Field(default="")


class FinanceAgent:
    """Bounded LangGraph finance agent.

    The graph gives the LLM autonomy over which approved tool to call and how to
    explain the result. Calculations and data access remain deterministic.
    """

    def __init__(self, session: Session, llm_provider: LLMProvider):
        from backend.agents.tools import FinanceTools

        self.llm_provider = llm_provider
        self.tools = FinanceTools(session)

        graph = StateGraph(AgentState)
        graph.add_node("plan_tool_call", self._plan_tool_call)
        graph.add_node("execute_tool", self._execute_tool)
        graph.add_node("synthesize_answer", self._synthesize_answer)
        graph.add_edge(START, "plan_tool_call")
        graph.add_edge("plan_tool_call", "execute_tool")
        graph.add_edge("execute_tool", "synthesize_answer")
        graph.add_edge("synthesize_answer", END)
        self.graph = graph.compile()

    def invoke(self, query: str) -> dict[str, Any]:
        """Answer one user query using an LLM-selected finance tool."""

        return self.graph.invoke({"user_query": query, "messages": [], "iteration_count": 0})

    def _plan_tool_call(self, state: AgentState) -> AgentState:
        system_prompt = (
            "You are the planning node for a local-first personal finance agent. "
            "Choose exactly one approved tool. Return only valid JSON with keys "
            "tool_name, tool_args, and reasoning. Do not answer the user yet."
        )
        user_prompt = json.dumps(
            {
                "user_query": state["user_query"],
                "available_tools": self.tools.prompt_schema(),
                "rules": [
                    "Use only listed tools.",
                    "Use ISO dates when supplying date filters.",
                    "Use get_monthly_summary for broad spending-over-time questions.",
                    "Use get_spending_by_category for category or budget composition questions.",
                    "Use search_transactions when the user asks for a merchant or description.",
                    "Use get_largest_transactions for biggest/largest transaction questions.",
                ],
            },
            indent=2,
        )
        raw_plan = self.llm_provider.complete(system_prompt, user_prompt)
        plan = ToolPlan.model_validate(_extract_json(raw_plan))
        available_tool_names = {tool["name"] for tool in self.tools.prompt_schema()}
        if plan.tool_name not in available_tool_names:
            raise ValueError(f"LLM requested an unknown finance tool: {plan.tool_name}")
        return {
            "selected_tool": plan.tool_name,
            "tool_args": plan.tool_args,
            "messages": state.get("messages", []) + [{"role": "assistant", "content": plan.reasoning}],
        }

    def _execute_tool(self, state: AgentState) -> AgentState:
        from backend.agents.tools import json_safe

        result = self.tools.execute(state["selected_tool"], state.get("tool_args", {}))
        return {"tool_result": json_safe(result)}

    def _synthesize_answer(self, state: AgentState) -> AgentState:
        system_prompt = (
            "You are Finance Guardian, a grounded personal finance analyst. "
            "Answer only from the provided tool result. If the result is empty, say that "
            "the imported data does not contain enough information yet. Do not invent "
            "numbers, transactions, categories, or dates."
        )
        user_prompt = json.dumps(
            {
                "user_query": state["user_query"],
                "tool_used": state["selected_tool"],
                "tool_args": state.get("tool_args", {}),
                "tool_result": state.get("tool_result"),
                "response_style": "Short answer first, then one useful detail if available.",
            },
            indent=2,
        )
        answer = self.llm_provider.complete(system_prompt, user_prompt).strip()
        return {"answer": answer}


def _extract_json(raw_text: str) -> dict[str, Any]:
    """Parse a model JSON response, accepting fenced JSON when necessary."""

    text = raw_text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match:
        text = fenced_match.group(1).strip()
    return json.loads(text)
