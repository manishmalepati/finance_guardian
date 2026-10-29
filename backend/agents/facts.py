"""Render numerical claims from verified service output, never from model prose."""

from typing import Any


def _fact(text: str, evidence: list[str] | None = None, link: str | None = None) -> dict:
    return {"id": "", "text": text, "transaction_ids": (evidence or [])[:12], "link": link}


def facts_for_tool(name: str, result: Any) -> list[dict]:
    if isinstance(result, list):
        if name == "get_monthly_summary":
            return [_fact(f"{item['month']} had {item['gross_posted_purchases']} {item['currency']} in gross settled purchases across {item['transaction_count']} transactions.")
                    for item in result[-4:]] or [_fact("No eligible monthly spending was found in the requested scope.")]
        if name == "get_spending_by_category":
            return [_fact(f"{item['category_id']} had {item['gross_posted_purchases']} {item['currency']} in gross settled purchases across {item['transaction_count']} transactions.")
                    for item in result[:4]] or [_fact("No eligible category spending was found in the requested scope.")]
        if name in {"get_largest_transactions", "search_transactions"}:
            return [_fact(f"{item['merchant']} had a settled purchase of {item['amount']} {item['currency']} on {item['posted_date']}.",
                          [item["id"]]) for item in result[:4]] or [_fact("No matching settled purchases were found in the requested scope.")]
        return [_fact(f"{name.replace('_', ' ')} returned {len(result)} records.")]
    if not isinstance(result, dict):
        return [_fact(f"{name.replace('_', ' ')} returned verified data.")]
    if name == "compare_spending_periods":
        currency = result["currency"]
        facts = [_fact(
            f"Gross settled purchases changed from {result['prior_total']} to {result['current_total']} {currency}; the difference is {result['delta']} {currency}.",
            link="intelligence")]
        for item in result.get("categories", [])[:3]:
            facts.append(_fact(
                f"{item['name']} contributed {item['delta']} {currency} to that change.",
                item.get("current_transaction_ids", []) + item.get("prior_transaction_ids", []), "intelligence"))
        for item in result.get("merchants", [])[:2]:
            facts.append(_fact(
                f"{item['name']} contributed {item['delta']} {currency} to the change.",
                item.get("current_transaction_ids", []) + item.get("prior_transaction_ids", []), "intelligence"))
        return facts
    if name in {"get_spending_forecast", "get_budget_risk"}:
        if result.get("forecast_total") is None:
            return [_fact("There is not enough eligible history for a defensible forecast.", link="forecast")]
        currency = result["currency"]
        facts = [_fact(
            f"{result['observed_to_date']} {currency} is posted this month; the estimated month-end total is {result['forecast_total']} {currency} using {result['method'].replace('_', ' ')}.",
            link="forecast")]
        if result.get("lower_bound") is not None:
            facts.append(_fact(
                f"The historical-error range is {result['lower_bound']}–{result['upper_bound']} {currency}; it is not a guaranteed interval.",
                link="forecast"))
        if result.get("budget"):
            facts.append(_fact(
                f"The current goal is {result['budget']} {currency}; status is {result['budget_status'].replace('_', ' ')}.",
                link="forecast"))
        return facts
    if name == "get_anomaly_summary":
        facts = [_fact(f"There are {result['alert_count']} behavioral alerts in the requested scope.",
                       link="behavioral-alerts")]
        for item in result.get("alerts", [])[:4]:
            facts.append(_fact(item["explanation"], item.get("supporting_transaction_ids", []),
                               "behavioral-alerts"))
        return facts
    if name == "get_recurring_charge_summary":
        facts = [_fact(f"There are {result['candidate_count']} recurring payment candidates in {result['currency']}.",
                       link="recurring-charges")]
        for item in result.get("candidates", [])[:4]:
            facts.append(_fact(item["reason"], item.get("transaction_ids", []), "recurring-charges"))
        return facts
    if name == "get_merchant_history":
        facts = [_fact(f"{result['count']} settled purchases matched {result['merchant_query']}; their gross total is {result['total']} {result['currency']}.",
                       [item["id"] for item in result.get("transactions", [])])]
        return facts
    if name == "get_categorization_summary":
        return [_fact(f"{result['categorized_transactions']} of {result['total_transactions']} transactions have categories; {result['uncategorized_transactions']} remain uncategorized.")]
    return [_fact(f"{name.replace('_', ' ')} returned verified data. Open the supporting result for details.")]


def collect_facts(tool_results: list[dict]) -> list[dict]:
    facts = []
    for tool in tool_results:
        if "result" not in tool:
            continue
        for fact in facts_for_tool(tool["name"], tool["result"]):
            fact["id"] = f"fact_{len(facts) + 1}"
            fact["source_tool"] = tool["name"]
            facts.append(fact)
            if len(facts) >= 12:
                return facts
    return facts
