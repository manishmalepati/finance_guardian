# Financial Guardian

Personal Finance Guardian helps you understand your transactions, analyze spending,
and ask grounded finance questions over local data.

## MVP Architecture

The first phase is a local-first modular monolith:

- `frontend`: React + TypeScript dashboard.
- `backend`: FastAPI, Plaid and targeted Gmail receipt ingestion, statement ingestion, analytics services, LangGraph agent, dbt CLI.
- `postgres`: durable local database backed by a Docker named volume.
- `dbt`: raw -> staging -> core -> marts transformations over source-agnostic transactions.
- `evals`: deterministic synthetic anomaly, forecast, categorization, and investigator evaluations, plus a separate optional live-agent suite.

The agent is intentionally bounded: it routes finance questions to approved read-only tools,
the tools calculate using code/SQL, and the backend renders final numerical facts.
The model may select fact IDs for a concise answer but cannot author its amounts.
Chat requires explicit local or cloud provider configuration.

## Local Setup

For a Windows host development environment, use an isolated Python environment
so that the repository's SQLAlchemy 2.x requirement does not resolve to an older
global installation:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend
npm.cmd ci
cd ..
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-dev.ps1
```

The verification script runs the backend unit tests and frontend TypeScript
check without connecting to Plaid, Gmail, or the local database. Pass
`-WithDocker` to additionally check that Docker Compose is reachable.

Create your environment file:

```bash
cp .env.example .env
```

Start the app:

```bash
docker compose up --build
```

Open:

- Frontend: http://localhost:3000
- Backend health: http://localhost:8000/health

Postgres data persists in the `postgres_data` Docker volume. `docker compose down`
keeps data; `docker compose down -v` removes it.

The v2 data model is Plaid-first and split into source-native and canonical layers:

- `raw.ingestion_runs`: one local ingest/sync event from Plaid or statement upload.
- `raw.plaid_items`: Plaid Item state, including the server-only access token and sync cursor.
- `raw.plaid_sync_runs`: one cursor-based Plaid transaction sync attempt per Item.
- `raw.plaid_transactions`: provider-native Plaid transaction payloads and sync evidence.
- `raw.statement_documents`: uploaded PDF statement files keyed by file hash.
- `raw.statement_transactions`: parsed statement rows with deterministic row hashes.
- `core.financial_accounts`: canonical account metadata, Plaid-backed where available.
- `core.transactions`: canonical transactions consumed by categorization, dbt, analytics, and the agent.
- `planning.goals`: recurring monthly category and subcategory spending targets.
- `planning.monthly_category_limits`: legacy limits retained for additive migration; goal records are now the writable source of truth.
- `receipt.*`: Gmail connection/sync state, minimal message provenance,
  normalized orders/items, and transaction-order match evidence.

See `docs/data-architecture-v2.md` for the identity model, PDF reconciliation
strategy, Plaid sync lifecycle, PFC mapping strategy, and planned LLM tool surface.

## Dashboard

The dark dashboard is organized into Overview, Transactions, Reports, Intelligence, Goals,
Accounts, and Settings. Overview shows posted spending, money in, and net flow as the main
figures. Pending amounts appear separately and are included in projected totals.
Known transfers and credit card payments appear as money movements, separate
from spending, money in, and net flow. Money in includes refunds; unclassified
transfers can still appear there until they are categorized.

Overview and Reports can be filtered to one canonical account or all accounts.
Reports has a date range, monthly cash-flow comparison, category trend, and
category share. Selecting a category opens its transactions with the same date
range and account filter. Transactions also supports account, date, category,
and search filters. Reports use posted amounts for trend and share charts.

Intelligence includes Explain My Spending: compare two selected periods, inspect
category and merchant contributions, separate purchase-count from average-amount
effects, and open the supporting transactions. Contributions reconcile exactly
to the change in gross posted purchase debits. See
`docs/spending-explanation.md` for exclusions, refund handling, and limitations.
It also shows possible recurring-charge patterns, estimated next dates, supporting
transactions, and persistent confirm/dismiss controls. See
`docs/recurring-charges.md` for the rules and limitations.
It also ranks unusually large settled charges against earlier history, supports
transaction drill-down, and saves expected/unexpected feedback. See
`docs/unusual-charges.md` for the statistical baseline, synthetic Isolation Forest
comparison, and the current absence of reviewed real-world labels.

The Intelligence page also shows completed-week purchase-frequency bursts,
sustained category spending increases, and recurring-price changes with evidence
and persistent reviews. The Forecast panel compares daily run rate and historical
monthly median using chronological cutoffs, shows a historical-error range only
when enough residuals exist, and describes current goal overrun status without
claiming a probability. The Financial Investigator can combine up to three
validated tools to answer a question with transaction links. These features
use gross settled purchase debits in one currency at a time. Credits and
possible refunds are excluded unless explicitly reconciled; known transfers,
pending, removed, superseded, and exact statement/Plaid duplicates are excluded.

| Capability | Status | Evaluation |
| --- | --- | --- |
| Robust amount, frequency, drift, recurring-price alerts | Served statistical rules | Four simple synthetic scenarios: 4/4 detected; no real-world precision estimate |
| Month-end spending forecast and goal status | Served statistical baselines | 18-month synthetic groceries series: historical median MAE $2.80 on 45 common cutoffs; sporadic travel abstains |
| TF-IDF plus logistic regression categorization | Offline experiment only | 144 easy synthetic examples: 100% on chronological and merchant-held-out tests; weak score calibration, no real-data claim |
| Isolation Forest anomaly benchmark | Offline experiment only | Separate transaction-level synthetic comparison; never served |
| Financial Investigator | Served when provider configured | Four fake-provider synthetic cases passed scope, evidence, and injection checks; no live-model quality estimate |

Architecture and learning guides: [architecture](docs/intelligence/architecture.md),
[execution plan](docs/intelligence/execution-plan.md),
[anomaly engineering](docs/intelligence/01-anomaly-engineering-guide.md),
[forecasting](docs/intelligence/02-forecasting-engineering-guide.md),
[ML categorization](docs/intelligence/03-ml-categorization-guide.md), and
[agent engineering](docs/intelligence/04-agent-engineering-guide.md).
Reproduce the experiments with `python -m evals.multi_signal_benchmark`,
`python -m evals.forecast_benchmark`, `python -m evals.categorization_experiment`,
and `python -m evals.investigator_benchmark` from the repository root.
All default datasets are synthetic. Local private training artifacts remain under
ignored `.local/models`; real transaction text is never sent to public evaluations.
Current checks could not reach local PostgreSQL, so live aggregate coverage and
the new migration persistence tests remain unverified in this environment.

Overview shows every spending category in a horizontally scrolling row of
bottom-filled tiles. An active category goal fills against its monthly cap;
projected overages get a red border and alert. Categories without goals use a
relative spending scale. The Goals page creates, edits, pauses, and removes
monthly category or subcategory targets, with posted progress, pending exposure,
transaction evidence, and a prior-month comparison. Goals always cover all
accounts. The Settings quick-limit editor writes the same goal records.

Goal definitions are recurring. The prior-month comparison applies the current
rule and threshold to prior transactions; this release does not preserve
historical versions of edited thresholds or categories. See
`docs/goals-design.md` for the calculation and extension design.

Analytics endpoints:

```text
GET /accounts
GET /analytics/spending-report?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD[&account_id=UUID]
GET /analytics/explain-spending?prior_start=YYYY-MM-DD&prior_end=YYYY-MM-DD&current_start=YYYY-MM-DD&current_end=YYYY-MM-DD[&account_id=UUID][&currency=USD]
GET /analytics/recurring-charges?as_of=YYYY-MM-DD[&account_id=UUID]
PUT /analytics/recurring-charges/{series_key}/review  {"decision": "confirmed", "as_of": "YYYY-MM-DD"}
GET /analytics/anomalies?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD[&currency=USD][&account_id=UUID]
PUT /analytics/anomalies/{transaction_id}/review  {"decision": "expected", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "currency": "USD"}
GET /analytics/behavioral-alerts?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD[&currency=USD][&account_id=UUID]
PUT /analytics/behavioral-alerts/{alert_id}/review  {"decision": "expected", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "currency": "USD"}
GET /analytics/spending-forecast?as_of=YYYY-MM-DD[&category_id=ID][&currency=USD][&account_id=UUID]
POST /agent/chat  {"message": "Why did my spending rise?", "account_id": null, "currency": "USD"}
GET /transactions?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD[&account_id=UUID][&category_id=ID]
```

Budget endpoints:

```text
GET    /budgets/monthly-limits
PUT    /budgets/monthly-limits/{category_or_subcategory_id}  {"amount": "500.00"}
DELETE /budgets/monthly-limits/{category_or_subcategory_id}

GET    /goals
POST   /goals  {"category_id": "CATEGORY_ID", "threshold_amount": "500.00", "timezone": "America/Los_Angeles"}
PATCH  /goals/{goal_id}  {"threshold_amount": "450.00", "status": "active"}
DELETE /goals/{goal_id}
GET    /goals/evaluations?month=YYYY-MM
GET    /goals/{goal_id}/evaluation?month=YYYY-MM
```

Startup applies additive receipt, goal, recurring-review, anomaly-review,
behavioral-review, and explicit-categorization-correction migrations to an existing database.
Keep the PostgreSQL volume when updating:

```bash
docker compose up --build
```

## Plaid Configuration

Plaid is the primary ingestion path. Statement upload remains as a fallback.

```bash
PLAID_CLIENT_ID=your_client_id
PLAID_SECRET=your_sandbox_secret
PLAID_ENV=sandbox
PLAID_PRODUCTS=transactions
PLAID_COUNTRY_CODES=US
PLAID_CLIENT_NAME=Finance Guardian
PLAID_VAULT_KEY=your_fernet_key
```

Generate `PLAID_VAULT_KEY` once and keep it in your ignored `.env` file:

```bash
docker compose exec backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Restart the backend after adding the key. It migrates existing Plaid access
tokens to encrypted database values and writes an encrypted vault at
`.local/plaid-vault-<environment>.enc`. The `.local` directory is bind-mounted
and survives `docker compose down -v`; preserve both the vault file and its key.
The vault is tied to the Plaid environment and client ID. Keep Sandbox and
Production credentials, keys, vaults, and data separate. Never commit the key
or vault, copy tokens into frontend code, or make unencrypted backups.
Docker exposes the frontend, API, and Postgres only on localhost. This is a
single-user local development setup; it has no application login.

After a database reset, startup restores the existing Plaid Items and attempts
to sync available history from a fresh cursor. If sync needs bank consent,
choose **Reauthenticate** on the existing institution and then sync again.
Do not start a new Link connection for the same bank. Plaid may not return older
history that is no longer available through the Item; preserve the database
when you need full history. Prefer migrations over resetting the database for
future schema changes.

Plaid [Sandbox](https://plaid.com/docs/sandbox/) permits unlimited test Items.
The [Trial plan](https://plaid.com/docs/account/billing/) permits 10 Production
Items total; removing an Item does not restore a slot. Repeated API calls on an
existing Item do not create another Item. Confirm your Plaid plan before using
real bank data.

## Gmail Receipt Development Setup

Create a Google Cloud OAuth client for a **Web application** in testing mode,
enable the Gmail API, and add only the intended development account as a test
user. Register this exact authorized redirect URI:

```text
http://localhost:8000/gmail/callback
```

Add these values to the ignored local `.env` file:

```text
GMAIL_CLIENT_ID=your_google_client_id
GMAIL_CLIENT_SECRET=your_google_client_secret
GMAIL_REDIRECT_URI=http://localhost:8000/gmail/callback
GMAIL_TOKEN_KEY=your_fernet_key
```

Generate the key locally with:

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The backend keeps the refresh token encrypted in PostgreSQL and never returns
it to the browser. Gmail OAuth requests the read-only Gmail scope, which grants
broader mailbox read access than receipts alone. The importer currently searches
order emails from `noreply@uber.com` with “Uber Eats” in the subject from the
last 90 days. It stores extracted order data and source metadata, but does not
keep complete message bodies. The observed Uber Eats emails contain a total and
date, but no item list; those fields remain unknown and matches require review.
Receipt reconciliation runs after both Gmail and Plaid syncs, including when
Gmail skips previously imported messages. Repeating either sync does not create
duplicate links. Automatic confirmation requires a complete receipt, exact
amount and currency, matching merchant, a date within one day, and no competing
order or transaction. Other candidates remain possible matches for review.
Disconnect can retain or delete the
locally extracted records. If Google revocation cannot be confirmed, the UI
reports that separately.

Receipt tables are created by an additive, versioned migration on backend
startup. Preserve the existing PostgreSQL volume and Plaid vault; a database
reset is not required.

### No-secrets demo

```powershell
docker compose -f docker-compose.demo.yml up --build
```

Open http://localhost:3100. The demo has its own PostgreSQL volume and uses
sanitized DoorDash and Uber Eats receipts with synthetic debits. It does not
mount `.env`, `.local`, or use live Plaid/Gmail credentials. The seeded
transactions can be opened from Transactions to inspect their linked orders
and items. Demo itemization is synthetic; the connected account's Uber Eats
emails currently expose only order totals in their message text.

After the demo stack is ready, run
`powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke-demo.ps1`
to check the seeded transactions, itemized receipts, matches, ledger total,
and parent/subcategory goal evaluations.
To exercise Gmail import and repeat-sync recovery with synthetic API responses against
the isolated demo database, run:

```powershell
$env:FG_DEMO_DATABASE_URL = 'postgresql+psycopg://finance_guardian_demo:finance_guardian_demo@127.0.0.1:5433/finance_guardian_demo'
.\.venv\Scripts\python.exe -m pytest backend/tests/test_gmail_sync_db.py backend/tests/test_receipt_reconciliation_db.py -q
Remove-Item Env:FG_DEMO_DATABASE_URL
```

Receipt workflow endpoints:

```text
GET    /gmail/status
POST   /gmail/connect
GET    /gmail/callback
POST   /gmail/sync
POST   /gmail/{connection_id}/disconnect
GET    /transactions/{transaction_id}/context
POST   /transactions/{transaction_id}/matches
DELETE /transactions/{transaction_id}/matches/{match_id}
GET    /receipts/orders
PATCH  /receipts/items/{item_id}
```

## Useful Commands

```bash
docker compose exec backend pytest backend/tests
docker compose exec backend dbt run --project-dir /app/dbt --profiles-dir /app/dbt
docker compose exec backend dbt test --project-dir /app/dbt --profiles-dir /app/dbt
docker compose exec backend python /app/evals/run.py
```

## Categorization Pipeline

Transactions are normalized into `core.transactions` from Plaid-first raw data
and secondary statement uploads. The backend enriches canonical transactions
through a fixed category taxonomy, merchant aliases, user corrections, and
optional LLM categorization for unknown merchants. dbt consumes the completed
enrichment rows and rebuilds analytics tables from deterministic joins.

Useful local endpoints:

```bash
curl -X POST http://localhost:8000/categorization/apply-known
curl -X POST http://localhost:8000/categorization/categorize-unknowns
curl http://localhost:8000/categorization/categories
curl http://localhost:8000/categorization/jobs
```

Useful database checks:

```bash
docker compose exec postgres psql -U finance_guardian -d finance_guardian -c "\dt enrichment.*"
docker compose exec postgres psql -U finance_guardian -d finance_guardian -c "select source, status, category_id, count(*) from enrichment.transaction_categorizations group by 1, 2, 3;"
```

## Agent Configuration

The app does not provide mock chat answers. Finance inference stays local by
default. To use a local or separately hosted trusted Ollama server:

```text
LLM_PROVIDER=ollama
LLM_MODEL=your_local_model
OLLAMA_BASE_URL=http://127.0.0.1:11434
FINANCE_LLM_PRIVACY=local_only
```

To explicitly allow finance data to reach Anthropic, configure:

```text
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-5
ANTHROPIC_API_KEY=your_key_here
FINANCE_LLM_PRIVACY=allow_cloud
```

There is no automatic cloud fallback if Ollama is unavailable. Provider requests
are bounded and transaction descriptions are treated as untrusted data. The
`OLLAMA_BASE_URL` address is reached from the backend process; when using Docker,
set it to a trusted host reachable from the backend container rather than assuming
that container localhost is your model host. Keep the Ollama listener private.
The optional live eval runner requires a configured provider and database; ordinary
tests use fake providers and make no paid calls. For a short product demo, run
the isolated synthetic demo stack, open **Intelligence**, compare two periods,
review behavioral alerts, inspect the month-end forecast, and ask the
Investigator a question after configuring a provider. Screenshots require a
running frontend and synthetic demo data; none are included in this checkout.

## License

Copyright (c) 2026 Manish Malepati. All rights reserved. This repository is
publicly available for portfolio and demonstration purposes. No permission is
granted to reproduce, distribute, modify, or use this software commercially
without prior written permission.
