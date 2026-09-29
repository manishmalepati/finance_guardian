import pytest

from backend.agents.graph import FinanceAgent, _extract_json
from backend.common.exceptions import AgentPlanningError


class FakeLLMProvider:
    """Test provider that returns a preselected model response."""

    def __init__(self, response: str):
        self.response = response

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self.response


class FakeTools:
    def prompt_schema(self):
        return [
            {"name": "get_monthly_summary", "description": "Monthly summary", "args_schema": {}},
            {"name": "get_largest_transactions", "description": "Largest transactions", "args_schema": {}},
        ]


def build_planner_only_agent(provider: FakeLLMProvider) -> FinanceAgent:
    agent = object.__new__(FinanceAgent)
    agent.llm_provider = provider
    agent.tools = FakeTools()
    return agent


def test_plan_tool_call_uses_llm_selected_tool():
    provider = FakeLLMProvider(
        '{"tool_name":"get_largest_transactions","tool_args":{"limit":5},"reasoning":"Need ranked spend."}'
    )
    agent = build_planner_only_agent(provider)

    state = agent._plan_tool_call({"user_query": "What are my biggest transactions?"})

    assert state["selected_tool"] == "get_largest_transactions"
    assert state["tool_args"] == {"limit": 5}


def test_plan_tool_call_rejects_unknown_tool():
    provider = FakeLLMProvider('{"tool_name":"run_sql","tool_args":{},"reasoning":"Unsafe."}')
    agent = build_planner_only_agent(provider)

    with pytest.raises(AgentPlanningError, match="unknown finance tool"):
        agent._plan_tool_call({"user_query": "Run SQL against my transactions"})


def test_plan_tool_call_rejects_invalid_json():
    provider = FakeLLMProvider("not json")
    agent = build_planner_only_agent(provider)

    with pytest.raises(AgentPlanningError, match="invalid tool plan"):
        agent._plan_tool_call({"user_query": "How did spending look?"})


def test_extract_json_accepts_fenced_json():
    assert _extract_json('```json\n{"tool_name":"get_monthly_summary","tool_args":{}}\n```') == {
        "tool_name": "get_monthly_summary",
        "tool_args": {},
    }
