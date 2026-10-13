# Data Architecture v2

Finance Guardian is now Plaid-first. Plaid is the primary transaction source,
and uploaded statements are supplemental evidence used for history backfills,
statement reconciliation, and audit trails.

## Layering

The database is split into source-native facts and canonical product facts:

- `raw`: provider payloads and document extraction results.
- `core`: canonical accounts and transactions used by the app.
- `enrichment`: categories, merchant aliases, and user/LLM categorization.
- `analytics`: dbt-derived marts for summaries, comparisons, and agent tools.

## Plaid-First Identity

Plaid IDs are first-class external keys, but local UUIDs remain primary keys.
This keeps the model flexible for PDF-only history, relinked Plaid Items,
manual records, and future providers.

- `raw.plaid_items.item_id`: Plaid Item identity and sync cursor.
- `core.financial_accounts.source_account_key`: Plaid account ID for Plaid accounts.
- `core.transactions.plaid_transaction_id`: unique Plaid transaction ID when present.
- `raw.plaid_transactions.plaid_transaction_id`: provider-native transaction record.
- `raw.plaid_sync_runs`: one attempted Plaid transaction sync for an Item.

`core.transactions` is the table that analytics, categorization, the API, and
LLM tools should read from. Raw Plaid rows point to the canonical transaction
through `canonical_transaction_id`.

## Plaid Sync Semantics

Plaid sync is cursor-based and must be applied atomically. The app requests
`/transactions/sync` with the saved Item cursor, applies all `added`, `modified`,
and `removed` changes across every page, and only advances the stored cursor
after the full sync succeeds. If any page or database write fails, the local
transaction rolls back and the previous cursor is retained.

If Plaid returns `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION`, the app rolls
back the partially applied pages and restarts the entire pagination loop from
the original cursor for that sync attempt. The sync request uses Plaid's maximum
page size of 500 to reduce pagination conflicts.

Sync-run audit records are durable even when the sync work rolls back:

- A `raw.ingestion_runs` row and `raw.plaid_sync_runs` row are committed before
  transaction pages are applied.
- Sync data changes, categorization, and cursor advancement happen in a separate
  transaction.
- On failure, the data transaction is rolled back and the run envelope is marked
  `failed` in a separate commit.
- On success, the run envelope is marked `completed` in the same transaction as
  the applied sync data and cursor advancement.

Plaid removals are soft deletes locally:

- `raw.plaid_transactions.removed_at` records when Plaid removed the transaction.
- `core.transactions.status = 'removed'` removes it from default analytics.
- Active categorization rows are preserved for audit/history instead of deleted.

Pending-to-posted transitions use Plaid's `pending_transaction_id`. When a posted
transaction references a prior pending transaction, the pending canonical row is
marked `superseded`, linked through `replaced_by_transaction_id`, and any active
category assignment is copied to the posted transaction unless the posted
transaction already has its own active category.

Default user-facing transaction lists read only transactions with
`status in ('active', 'pending')`.

Analytics distinguish settled reports from fresh estimates:

- Existing headline totals include active posted and pending transactions.
- `posted_*` fields include only settled transactions.
- `pending_*` fields include pending transactions.
- Financial reports should use posted fields by default; dashboard previews may
  use headline totals to include pending activity.

## Plaid Personal Finance Categories

Plaid Personal Finance Categories are preserved as source suggestions, not used
as the app's canonical taxonomy. Plaid publishes the full PFC taxonomy as a CSV
from its docs, and the app maps PFC detailed categories into
`enrichment.category_taxonomy` through `enrichment.plaid_category_mappings`.

The current categorization precedence is:

```text
user override / alias > seed alias > Plaid PFC mapping > LLM queue > uncategorized
```

The Plaid sync request opts into PFCv2 with
`options.personal_finance_category_version = 'v2'`. Raw Plaid PFC values are
stored on both `raw.plaid_transactions` and `core.transactions` so mappings can
be revised and reapplied later.

## Statement Uploads

PDF uploads are deliberately secondary. A statement import creates:

- `raw.statement_documents`: one row per uploaded file, keyed by file hash.
- `raw.statement_transactions`: one row per parsed statement row.
- `core.transactions`: fallback canonical transactions created from statement
  rows until a reconciliation process matches them to Plaid transactions.

Statement row identity is deterministic:

```text
sha256(file_hash + row_number + posted_date + normalized_description + amount + direction)
```

That means the same PDF import can be detected as a duplicate, and individual
statement rows have stable identities even before they are matched to Plaid.

## Reconciliation Direction

The next reconciliation layer should compare statement rows against canonical
Plaid transactions using account, date window, amount, direction, and normalized
description. Outcomes should be explicit:

- `matched`: statement row confirms an existing Plaid transaction.
- `statement_only`: transaction exists in a statement but not in Plaid.
- `plaid_only`: transaction exists in Plaid but not in the statement period.
- `ambiguous`: multiple plausible matches need review.

When a statement row is matched to a Plaid transaction, it should point to the
existing `core.transactions.id` instead of creating a duplicate canonical row.

## LLM Tool Implications

The LLM should never receive database access. It should use bounded tools over
`core` and `analytics` data:

- `get_spending_summary(start_date, end_date, group_by)`
- `search_transactions(query, filters)`
- `get_merchant_history(merchant_name, date_range)`
- `get_recurring_transactions()`
- `get_income_summary(start_date, end_date)`
- `compare_periods(period_a, period_b, dimensions)`
- `find_anomalies(start_date, end_date)`
- `get_budget_status(month)`
- `get_statement_reconciliation(statement_id)`

This implies durable feedback tables in later phases for budgets, merchant
aliases, transaction annotations, recurring-series confirmations, exclusions,
and user category overrides.

## Local Migration

This branch intentionally changes schema shape. For local development, drop and
recreate the database volume after merging schema changes:

```bash
docker compose down -v
docker compose up --build
```
