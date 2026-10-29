# Financial Investigator engineering guide

## 1. Product problem

People ask multi-part questions such as “Why did spending rise, and am I likely to exceed my grocery goal?” A single raw database result rarely answers both parts. The Investigator lets a model choose up to three approved read-only tools, then returns only backend-rendered financial facts with transaction links and analysis links. It cannot write transactions, run arbitrary SQL, or author final numeric claims.

## 2. Data and tool boundaries

The tools call existing services: `SpendingExplanationService` for reconciled gross purchase comparisons, `MultiSignalAnomalyService` for behavioral alerts, `RecurrenceService` for recurring candidates, `ForecastService` for month-end estimates and current goal status, and `CategorizationService` for coverage. Legacy monthly, category, largest-purchase, and search tools now use the shared settled-purchase eligibility layer with account/currency/date scopes. The source is canonical `core.transactions` plus current active categorization and analytics review tables; exact historical ingestion and category snapshots remain unavailable. All tool parameters have Pydantic schemas, date and result limits, and PostgreSQL statement timeouts.

Transaction descriptions and merchant names are untrusted evidence. They can be shown as data, but cannot alter the tool list, schema, or final rendering instructions. Decimal values are serialized as strings, not floats. The backend computes every amount. Retrieved tool results are bounded before the second model prompt.

## 3. Orchestration algorithm

`FinanceAgent` in `backend/agents/graph.py` uses a three-stage LangGraph: plan, execute, synthesize. The plan is JSON containing one to three approved tool calls. Unknown, duplicate, excessive, or invalid plans are rejected. The account and currency selected in the UI override any model-supplied values. Tool execution validates arguments and records partial failures. The synthesis step builds a maximum of 12 factual statements in `backend/agents/facts.py` from service output. The model may return **fact IDs only**, selecting up to six statements. The backend constructs the final answer from the selected statements. If selection fails, it uses the first verified facts; if no tools succeeded, it says it cannot verify an answer. This is deterministic grounding rather than trusting free-form model prose.

Pseudocode:

```text
plan = validate_model_json(question, tool_schemas, user_scope)
assert 1 <= len(plan.calls) <= 3 and all calls are approved
for call in plan.calls:
    validate schema; run read-only service with bounded output and timeout
facts = render_exact_claims_from_service_results(maximum=12)
selected_ids = model_select_fact_ids(facts) or first_verified_ids
answer = concatenate(facts[id].text for selected ids)
return answer, evidence transaction IDs, analysis links, partial-error notices
```

The graph has three nodes, a recursion limit of five, and an overall 30-second deadline. Provider requests have a 20-second HTTP timeout; PostgreSQL tool statements have a 5-second timeout. Python cannot forcibly stop a database operation outside PostgreSQL, so the database limit is important. This remains a single-agent workflow with no autonomous loop.

## 4. Privacy and provider selection

`FINANCE_LLM_PRIVACY=local_only` is the default. With `LLM_PROVIDER=anthropic`, finance chat and LLM categorization require the explicit setting `FINANCE_LLM_PRIVACY=allow_cloud` plus a configured key. With `LLM_PROVIDER=ollama`, set `LLM_MODEL` and optionally `OLLAMA_BASE_URL` for a separate trusted host. The default Ollama URL binds to localhost in this app configuration; the application does not launch or expose an Ollama server. There is no cloud fallback if Ollama is unavailable. The selected provider receives the user question and bounded fact text; never use live account data in public model experiments.

## 5. Evaluation

Run `python -m evals.investigator_benchmark`. Four deterministic synthetic cases cover two-tool planning, prompt injection in a merchant field, insufficient forecast data, and a partial tool failure. Current measured results: exact tool selection 4/4, required fact completeness 4/4, evidence coverage 4/4, scope parameter accuracy 4/4, injected numeric claim rate 0/4, and 1.5 average tool calls. Fake-provider latency ranged about 3–10 ms locally; it does not represent live model latency. Token usage was unavailable. `backend/tests/test_financial_investigator.py` also checks duplicate/unknown plans, date and limit validation, exact Decimal preservation, gross-debit tool aggregation, explicit cloud opt-in, and mocked Ollama response handling. Existing agent planning tests still pass.

No live Anthropic or Ollama calls were made. The local PostgreSQL connection was unavailable, so end-to-end investigator answers over live database rows and API persistence could not be checked here. The old `evals/run.py` remains a separate live-model tool-selection suite and requires an explicitly configured provider.

## 6. Tradeoffs and limitations

Returning backend-rendered statements prevents invented numeric claims, but it limits narrative flexibility. A model can still select less relevant true facts; deterministic evaluations measure this on known questions, while live-model evaluation remains necessary. Tool output may include a merchant string containing misleading instructions; the selection output is parsed as IDs and other text is ignored. Current account filtering is a local single-user scope, not an authorization system. This project has no multi-user authentication. Current budget comparisons use the present goal definition; edited goal history is not reconstructed.

## 7. Improvements

Add more synthetic and consented real questions with independently checked answers, measure live-model tool choice and relevance, and record provider latency/token usage without logging finance payloads. Add richer fact templates for refunds and pending exposure, and historical data snapshots for strict point-in-time answers. Before supporting write actions, add a separate authorization workflow. Treat external/local model output as untrusted even when it appears well formatted.

## 8. Interview preparation

1. **Why use bounded tools?** They constrain the model to validated financial calculations and prevent arbitrary database access.
2. **How are hallucinated amounts prevented?** The model selects fact IDs; the backend renders all numeric text from service results.
3. **Why is a tool result untrusted?** Transaction descriptions and merchant fields can contain attacker-written instructions.
4. **How is a multi-step question handled?** The model plans up to three approved calls; each result contributes verified facts and evidence.
5. **What is the privacy boundary?** Local inference is the default; cloud inference requires explicit configuration and has no silent fallback.
