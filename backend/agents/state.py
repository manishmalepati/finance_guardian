from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """State shared by LangGraph nodes during one chat request."""

    messages: list[dict[str, str]]
    user_query: str
    selected_tool: str
    tool_args: dict[str, Any]
    tool_result: Any
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    facts: list[dict[str, Any]]
    evidence_transaction_ids: list[str]
    tools_used: list[str]
    deadline: float
    scope: dict[str, Any]
    answer: str
    errors: list[str]
    iteration_count: int
