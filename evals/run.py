from pathlib import Path
import sys

import yaml

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backend.agents.graph import FinanceAgent


class RouteOnlyAgent(FinanceAgent):
    def __init__(self):
        pass


def main() -> int:
    cases = yaml.safe_load(Path("evals/cases.yaml").read_text())["cases"]
    failures: list[str] = []
    agent = RouteOnlyAgent()
    for case in cases:
        result = agent._route({"user_query": case["query"]})
        if result["selected_tool"] != case["expected_tool"]:
            failures.append(
                f"{case['id']}: expected {case['expected_tool']}, got {result['selected_tool']}"
            )

    if failures:
        print("Eval failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"All {len(cases)} routing evals passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
