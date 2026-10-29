# Spending forecasting engineering guide

## 1. Product problem

The Forecast panel estimates total **gross settled purchase debits** by the end of the selected calendar month. It separates spending already observed from estimated remaining spending. A category goal produces a descriptive projected-over-budget status, never an unsupported exceedance probability. Sparse, sporadic scopes can return insufficient data.

## 2. Data and grain

The observation grain is one account/currency/category/month forecast at a chosen cutoff day. `core.transactions` and the latest active `enrichment.transaction_categorizations` row provide amount, posted date, account, currency, merchant, and category. `AnomalyService.purchase_rows()` prepares the join and `eligible_purchases()` applies the same settled-debit rules used by anomalies: pending, removed, superseded, credits, known transfers, and exact statement/Plaid overlap are excluded. Parent-category requests include current child taxonomy IDs. Active `planning.goals` with matching category and currency supply the current monthly limit; their past values are not assumed for historical months. Confirmed upcoming recurring charges from `RecurrenceService` are shown separately because a monthly baseline may already include them.

Month totals use Decimal. Missing days within a month count as zero observed spending, but the system cannot prove continuous account ingestion coverage. Historical category revisions and later bank backfills cannot be reconstructed, so backtests are idealized posted-date evaluations.

## 3. Algorithms from first principles

### Daily run rate

`forecast = spending_so_far / elapsed_days × days_in_month`. If $50 is posted by day 10 of a 30-day month, the run rate projects $150. It assumes the observed daily pace continues, which fails for rent, pay-cycle purchases, and one-off expenses. `forecast_rows()` never forecasts below spending already observed.

### Historical monthly median

With at least three completed historical months, take the median of up to 12 previous monthly gross totals. If prior totals are $90, $100, and $140, the median is $100. The median resists a one-off large month. The forecast is at least the amount already spent. This baseline misses sustained trend and seasonality.

### Walk-forward model selection

`backtest_rows()` in `backend/services/forecasting.py` replays cutoffs on days 7, 15, and 22 of completed months. At each cutoff, candidate features use only transactions posted by that day; the completed month total is used only as the evaluation target. The methods are compared using **matching cutoff cases**. Mean absolute error is `sum(abs(predicted - actual)) / cases`. WAPE is `sum(abs(error)) / sum(actual)` and is omitted when actual total is zero. At least six cases are required to call a method evaluated; otherwise the result is provisional. No complex model is served because the available local real-data coverage could not be checked.

### Uncertainty

The interval margin is the empirical 80th percentile of prior absolute backtest errors. A $100 forecast with a $15 margin gives $85–$115, with the lower bound raised to observed spending if needed. Historical interval evaluation uses only errors from **older months**; a same-month final total cannot calibrate an earlier cutoff. Coverage is the share of actual completed totals falling inside these historical ranges. These are rough error ranges, not calibrated 80% probability intervals. Fewer than six residuals means no range is shown.

### Budget status

If observed spending already exceeds a matching current goal, status is `already_over_budget`. Otherwise, if the forecast exceeds it, status is `projected_over_budget`; else `currently_within_budget`. The overshoot is `max(0, forecast - budget)`. For a $100 forecast and $90 goal, the overshoot is $10. No probability is claimed. Historical budget backtesting is omitted because goal version history is unavailable.

Pseudocode: `select eligible purchases → scope account/currency/category → compute current subtotal and prior month totals → replay historical cutoffs → choose lower-MAE baseline on common cases → derive error range if enough older residuals → compare with current goal → return evidence and limitations`.

## 4. Application flow

`Transaction → purchase_rows() → eligible_purchases() → forecast_rows()/backtest_rows() → ForecastService → GET /analytics/spending-forecast → ForecastPanel`. The API validates as-of date, currency, account UUID, and category ID. The UI shows observed, remaining, total, historical-error range, method, category breakdown, current goal status, and confirmed upcoming recurring charges. `backend/tests/test_forecasting.py` covers method choice, chronological cutoffs, currency/account/category isolation, pending/credit exclusions, no history, and sporadic abstention.

## 5. Evaluation

Run `python -m evals.forecast_benchmark` from the repository root. Its deterministic 18-month synthetic groceries series has 45 common comparison cutoffs: historical median MAE $2.80 and WAPE 0.023; run rate MAE $6.21 on those same cases. The historical method's prior-error interval covered 39/39 evaluated cutoffs with mean width $8.00 on this simple synthetic pattern. The selected July forecast at day 15 is $124 with a $120–$128 historical-error range. A quarterly travel series is not served for July because it has no current purchases and fewer than half of historical months are active; the offline backtest still reports historical-median MAE $28.33 and WAPE 0.405. These values are from synthetic patterns, not live financial accuracy. The local PostgreSQL connection was unavailable during this work.

## 6. Tradeoffs

Simple baselines are inspectable and can be evaluated on limited histories. A gradient-boosted regressor would need more independent months and careful temporal validation. The service computes forecasts on request instead of storing a model artifact. Parent-category membership is based on the current taxonomy; historical remapping remains a limit. A monthly median can forecast zero for intermittent spending, so sporadic scopes with no current activity abstain. Confirmed recurring charges are presented as context, not added on top of a baseline that may already include them.

## 7. Improvements

Record ingestion coverage and category versions so historical replay can be strict point-in-time. Compare seasonal-naive and exponentially smoothed baselines when enough completed months exist. Add goal version history before evaluating historical budget risk. Measure intervals on real, consented, fully covered account histories before describing them probabilistically.

## 8. Interview preparation

1. **Why use WAPE instead of MAPE?** MAPE becomes undefined or unstable when an individual actual month is zero; WAPE aggregates the denominator.
2. **What is walk-forward evaluation?** Repeatedly pretend a past date is today, predict using only earlier data, and compare with the later outcome.
3. **Why compare methods on common cutoffs?** Different case populations can make MAEs incomparable.
4. **Why do intervals need older residuals?** Using a month's final actual to calibrate its own earlier prediction leaks future information.
5. **Why is budget risk nonprobabilistic?** No validated predictive distribution or historical goal versions support an exceedance probability.
