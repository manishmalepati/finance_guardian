# finance_guardian

Personal Finance Guardian helps you understand your transactions, analyze spending,
and ask grounded finance questions over local data.

## MVP Architecture

The first phase is a local-first modular monolith:

- `frontend`: React + TypeScript dashboard.
- `backend`: FastAPI, Plaid ingestion, statement ingestion, analytics services, LangGraph agent, dbt CLI.
- `postgres`: durable local database backed by a Docker named volume.
- `dbt`: raw -> staging -> core -> marts transformations over source-agnostic transactions.
- `evals`: small live-agent eval suite for tool choice and grounded responses.

The agent is intentionally bounded: it routes finance questions to approved tools,
the tools calculate using code/SQL, and the agent synthesizes the answer. Chat
requires a real LLM provider configuration and returns an error until one is set.

## Local Setup

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

The current raw model is intentionally source-agnostic:

- `raw.ingestion_runs`: one local ingest/sync event from Plaid or statement upload.
- `raw.plaid_items`: Plaid Item state, including the server-only access token and sync cursor.
- `raw.financial_accounts`: source account metadata normalized across providers.
- `raw.transactions`: canonical raw transactions consumed by categorization, dbt, analytics, and the agent.

For a clean local rebuild after schema changes:

```bash
docker compose down -v
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
```

Sandbox test credentials can be used through Plaid Link. For production hardening,
encrypt Plaid access tokens before storing them outside a local development database.

## Useful Commands

```bash
docker compose exec backend pytest backend/tests
docker compose exec backend dbt run --project-dir /app/dbt --profiles-dir /app/dbt
docker compose exec backend dbt test --project-dir /app/dbt --profiles-dir /app/dbt
docker compose exec backend python /app/evals/run.py
```

## Categorization Pipeline

Transactions are imported into `raw.transactions` unchanged. The
backend enriches them through a fixed category taxonomy, merchant aliases, user
corrections, and optional LLM categorization for unknown merchants. dbt consumes
the completed enrichment rows and rebuilds analytics tables from deterministic
joins.

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

The app does not provide mock chat answers. Configure Claude before using
`POST /agent/chat`:

```bash
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-5
ANTHROPIC_API_KEY=your_key_here
```

The eval runner also requires this configuration because it exercises the real
agent path. The MVP keeps Claude responses capped at 300 output tokens to limit
cost and keep answers concise.

## License

Copyright (c) 2026 Manish Malepati. All rights reserved. This repository is
publicly available for portfolio and demonstration purposes. No permission is
granted to reproduce, distribute, modify, or use this software commercially
without prior written permission.
