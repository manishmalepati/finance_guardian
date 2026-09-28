from pathlib import Path
import sys

import yaml

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backend.agents.graph import FinanceAgent
from backend.db.session import SessionLocal, init_database


def main() -> int:
    init_database()
    cases = yaml.safe_load(Path("evals/cases.yaml").read_text())["cases"]
    failures: list[str] = []
    with SessionLocal() as session:
        agent = FinanceAgent(session)
        for case in cases:
            result = agent.invoke(case["query"])
            if result["selected_tool"] != case["expected_tool"]:
                failures.append(
                    f"{case['id']}: expected {case['expected_tool']}, got {result['selected_tool']}"
                )
            answer = result.get("answer", "").lower()
            for phrase in case.get("must_include", []):
                if phrase.lower() not in answer:
                    failures.append(f"{case['id']}: answer missing phrase {phrase!r}")

    if failures:
        print("Eval failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"All {len(cases)} evals passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
