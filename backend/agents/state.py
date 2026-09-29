from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """State shared by LangGraph nodes during one chat request."""

    messages: list[dict[str, str]]
    user_query: str
    selected_tool: str
    tool_args: dict[str, Any]
    tool_result: Any
    answer: str
    errors: list[str]
    iteration_count: int
