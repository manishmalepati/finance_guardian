from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from backend.agents.state import AgentState


class FinanceAgent:
    def __init__(self, session: Session):
        from backend.agents.tools import FinanceTools

        self.tools = FinanceTools(session)
        graph = StateGraph(AgentState)
        graph.add_node("route", self._route)
        graph.add_node("execute_tool", self._execute_tool)
        graph.add_node("synthesize", self._synthesize)
        graph.add_edge(START, "route")
        graph.add_edge("route", "execute_tool")
        graph.add_edge("execute_tool", "synthesize")
        graph.add_edge("synthesize", END)
        self.graph = graph.compile()

    def invoke(self, query: str) -> dict[str, Any]:
        return self.graph.invoke({"user_query": query, "messages": [], "iteration_count": 0})

    def _route(self, state: AgentState) -> AgentState:
        query = state["user_query"].lower()
        if "largest" in query or "biggest" in query:
            return {"selected_tool": "get_largest_transactions", "tool_args": {"limit": 10}}
        if "category" in query or "food" in query or "grocer" in query:
            return {"selected_tool": "get_spending_by_category", "tool_args": {}}
        if "find" in query or "search" in query:
            cleaned = query.replace("find", "").replace("search", "").strip()
            return {"selected_tool": "search_transactions", "tool_args": {"query": cleaned or query}}
        return {"selected_tool": "get_monthly_summary", "tool_args": {}}

    def _execute_tool(self, state: AgentState) -> AgentState:
        tool_name = state["selected_tool"]
        args = state.get("tool_args", {})
        tool = getattr(self.tools, tool_name)
        return {"tool_result": tool(**args)}

    def _synthesize(self, state: AgentState) -> AgentState:
        tool = state["selected_tool"]
        result = state.get("tool_result", [])
        if not result:
            labels = {
                "get_largest_transactions": "largest transactions",
                "get_spending_by_category": "category spending",
                "search_transactions": "transaction search",
                "get_monthly_summary": "monthly summary",
            }
            answer = (
                f"I do not see data for {labels.get(tool, 'that request')} yet. "
                "Import a Chase statement first, then ask again."
            )
        elif tool == "get_largest_transactions":
            top = result[0]
            answer = (
                f"Your largest recorded transaction is {top['description']} for ${top['amount']} "
                f"on {top['posted_date']}. I found {len(result)} transactions in the ranked list."
            )
        elif tool == "get_spending_by_category":
            top = result[0]
            answer = (
                f"Your highest spending category is {top['category']} at ${top['amount']:.2f}. "
                f"This is based on {top['transaction_count']} debit transactions."
            )
        elif tool == "search_transactions":
            answer = f"I found {len(result)} matching transactions. The first match is {result[0]['description']}."
        else:
            latest = result[-1]
            answer = (
                f"Latest monthly summary: {int(latest['year'])}-{int(latest['month']):02d} had "
                f"${latest['debits']:.2f} debits, ${latest['credits']:.2f} credits, and "
                f"${latest['net_spend']:.2f} net spend."
            )
        return {"answer": answer}
