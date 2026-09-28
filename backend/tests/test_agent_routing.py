from backend.agents.graph import FinanceAgent


class FakeAgent(FinanceAgent):
    def __init__(self):
        pass


def test_routes_largest_transactions():
    agent = FakeAgent()
    state = agent._route({"user_query": "What are my biggest transactions?"})
    assert state["selected_tool"] == "get_largest_transactions"


def test_routes_category_spending():
    agent = FakeAgent()
    state = agent._route({"user_query": "How much did I spend by category?"})
    assert state["selected_tool"] == "get_spending_by_category"


def test_routes_default_monthly_summary():
    agent = FakeAgent()
    state = agent._route({"user_query": "How did last month look?"})
    assert state["selected_tool"] == "get_monthly_summary"
