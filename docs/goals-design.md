# Monthly goals design

## Boundaries and data flow

`planning.goals` owns recurring goal definitions. `backend/goals/service.py` is
the application boundary for validation, persistence, and evidence retrieval.
`backend/goals/evaluation.py` holds pure calculation rules. The FastAPI Goals
routes expose the service; the existing Budgets routes are a compatibility
facade over the same records. Overview and Goals read goal evaluations, while
Settings quick limits use the facade. Receipts enrich transactions but never
contribute a second monetary charge to a spending goal.

The SQL migration copies existing `planning.monthly_category_limits` into
`planning.goals` once, with USD and UTC as the legacy defaults. It does not
delete the old rows. New edits only change goals. One spending target per
category or subcategory avoids conflicting caps for the same scope.

## Rules

- A parent category includes direct assignments and every child subcategory.
  A subcategory includes only that exact child. Parent and child goals can
  coexist; they are separate views of the same ledger activity and must not be
  summed as independent spending.
- Only active or pending canonical bank transactions dated inside the chosen
  calendar month are considered. The IANA time zone chooses the current month
  when the caller omits it. `posted_date` is a date in the existing canonical
  model, so this release cannot reassign a transaction across month boundaries
  based on its original timestamp alone.
- Posted net spend is scoped debits minus scoped credits, floored at zero.
  Credits reduce the total but are not asserted to be verified refunds.
  Pending net is separate and affects only projected spend. Removed or
  superseded transactions do not count.
- A goal uses one currency. Transactions with unknown or different currency
  are excluded and counted in the response. No implicit FX conversion occurs.
  Each evaluation returns transaction IDs, amounts, period bounds, evaluation
  time, exclusions, and caveats.
- The dashboard tile fill is projected spend divided by the active threshold,
  capped visually at 100%. It marks an overage when the uncapped projection
  exceeds the threshold and distinguishes posted from projected overages.
  The Goals page also shows posted values and evidence.
- Prior-month comparison evaluates the same **current** rule against the prior
  month's ledger. Editing a goal changes this comparison retroactively because
  goal versions are not stored yet. Pausing suppresses the active budget cue
  but retains the definition and its evidence view.

## Extension points

The `GoalMetric` protocol and `METRICS` registry isolate calculations by goal
type. `ScopeRule` and `SCOPES` isolate inclusion rules. `GoalService` owns the
database query and hands `EvidenceRow` objects to a metric; API and UI consume
the returned evaluation contract. A future delivery-frequency goal will need
an explicit order/transaction deduplication policy, period and unit fields,
schema migration, validation, and tests before it is registered. It should not
reuse the spending sum or treat an unmatched email as a confirmed purchase.

The present query evaluates each goal separately, which is acceptable for a
small local goal set. A future optimization can fetch the month's evidence once
and evaluate multiple rules in memory without changing the calculation
contract. Persisted goal revisions and evaluation snapshots can be added when
historical target accuracy is needed; they are not represented as existing
behavior in this release.

## Verification

`backend/tests/test_goals.py` covers scope, credits, pending exposure, currency,
time zone, and period boundaries. `backend/tests/test_goals_db.py` exercises
the budget facade, pause/resume state, evidence, and legacy-limit migration
against the isolated demo PostgreSQL database. `scripts/smoke-demo.ps1` checks
synthetic parent and child goals alongside the receipt and transaction flow.
