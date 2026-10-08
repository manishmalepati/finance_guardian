# finance_guardian

Personal Finance Guardian helps you understand your transactions, analyze spending,
and ask grounded finance questions over local data.

## MVP Architecture

The first phase is a local-first modular monolith:

- `frontend`: React + TypeScript dashboard.
- `backend`: FastAPI, ingestion, analytics services, LangGraph agent, dbt CLI.
- `postgres`: durable local database backed by a Docker named volume.
- `dbt`: raw -> staging -> core -> marts transformations.
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

## Useful Commands

```bash
docker compose exec backend pytest backend/tests
docker compose exec backend dbt run --project-dir /app/dbt --profiles-dir /app/dbt
docker compose exec backend dbt test --project-dir /app/dbt --profiles-dir /app/dbt
docker compose exec backend python /app/evals/run.py
```

## Categorization Pipeline

Transactions are imported into `raw.statement_transactions` unchanged. The
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
