from pathlib import Path
import sys

import yaml

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backend.agents.graph import FinanceAgent
from backend.core.config import settings
from backend.db.session import SessionLocal, init_database
from backend.llm.providers import LLMProviderFactory


def main() -> int:
    """Run a tiny live-agent eval suite.

    These evals intentionally require a configured LLM. Without one, the script
    exits clearly instead of running a fake or static substitute.
    """

    configuration_error = settings.agent_configuration_error()
    if configuration_error:
        print(f"Cannot run agent evals: {configuration_error}")
        return 2

    init_database()
    cases = yaml.safe_load(Path("evals/cases.yaml").read_text())["cases"]
    failures: list[str] = []
    provider = LLMProviderFactory(settings).build()

    with SessionLocal() as session:
        agent = FinanceAgent(session, llm_provider=provider)
        for case in cases:
            result = agent.invoke(case["query"])
            if result["selected_tool"] != case["expected_tool"]:
                failures.append(
                    f"{case['id']}: expected {case['expected_tool']}, got {result['selected_tool']}"
                )
            if not result.get("answer", "").strip():
                failures.append(f"{case['id']}: answer was empty")

    if failures:
        print("Eval failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"All {len(cases)} live agent evals passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
