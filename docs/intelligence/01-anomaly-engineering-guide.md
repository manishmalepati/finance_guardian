# Multi-signal anomaly engineering guide

## 1. Product problem

A large single purchase, an unusual number of ordinary purchases, a sustained increase in category spending, and a recurring bill increase are different behaviors. The Intelligence page now presents each signal with its own evidence and Expected/Unexpected review. A signal describes a change in observed behavior. It is neither a fraud finding nor a probability.

## 2. Data and observation grain

`core.transactions` supplies canonical ID, account, posted date, amount, direction, currency, status, source, and pending/replacement/removed flags. The latest active `enrichment.transaction_categorizations` row supplies category and normalized merchant. `analytics.recurring_reviews` supplies confirmed or dismissed series status; `analytics.behavioral_alert_reviews` stores a review keyed by stable alert ID. `AnomalyService.purchase_rows()` performs the cardinality-safe join. `eligible_purchases()` in `backend/domain/transaction_eligibility.py` retains active settled positive debits, excludes known transfers and card payments, and pairs exact statement/Plaid overlap by occurrence. Credits and refunds remain excluded from gross spending. Currency and account are filtered before statistics are computed.

The grains are transaction for amount, merchant/account/week and category/account/week for frequency, category/account/week for drift, and merchant/account/currency recurring series for price. Weeks begin Monday and end Sunday. Only completed weeks are evaluated. Historical cutoffs use strictly earlier posted dates for amount and earlier completed weeks for period signals. This is an idealized posted-date reconstruction: ingestion timestamps and historical category versions are not recorded at every cutoff.

## 3. Algorithms from first principles

### Amount: robust median and MAD

The existing `score_purchases()` compares a purchase with earlier purchases at the same merchant, then category, then account when enough history exists. The median is the middle amount. MAD is the median absolute distance from that median. A robust scale is `max(1.4826 × MAD, 0.15 × median, 2)`. An $80 charge after five $10 charges has median $10, MAD $0, scale $2, and score `(80 - 10) / 2 = 35`; absolute and relative gates must also pass. The scale floor prevents infinite scores. Pseudocode: `for purchase by date: choose first sufficient prior-only reference; compute median and MAD; emit if all gates pass; append purchase to history`. The median is less distorted by a past spike than the mean. Sparse merchants use category or account history, but this can be less personally relevant.

### Frequency: rolling completed-week counts

`_frequency()` in `backend/services/multi_signal_anomalies.py` counts purchases in the previous eight completed weeks, including zero-count weeks. It requires at least four active reference weeks. The current completed week must have at least four purchases and exceed both twice the historical median and `median + max(3, 3 × MAD)`. For weekly counts `2,1,2,2,1,2,2,2`, median is 2 and MAD is 0; eight purchases exceeds both gates. Pseudocode: `for entity and complete week: gather eight earlier week counts; abstain if too sparse; compare current count; emit evidence`. This is an explainable screening rule, not a Poisson claim. Irregular normal behavior can still generate alerts.

### Drift: sustained weekly level shift

`_drift()` takes the median of eight historical category-week totals and requires three consecutive completed weeks at least 25% and $10 above that level. It emits once at the start of an episode by checking that the preceding week was below the threshold. For eight $80 weeks followed by $120, $120, $120, the baseline is $80 and the sustained level is $120. The detector reports whether the increase appears mainly driven by purchase count or average purchase size. Pseudocode: `for category and week: compare the last three completed weeks with eight older weeks; require prior coverage; suppress continuing episode`. A gradual rise can be missed if it never forms a three-week level shift; EWMA and CUSUM are reasonable future comparisons.

### Recurring price

`detect_signals()` reuses `detect_candidates()` from `backend/services/recurrence.py`, which establishes timing cadence and amount stability for a merchant/account/currency series. The latest amount must rise at least 10% and $1 above the previous typical amount. Four monthly payments of $10, $10, $10, $12 yield a $2 or 20% increase. The alert calls an unconfirmed series a candidate. If an amount alert already explains the same latest transaction, the price alert is suppressed to reduce duplicate review work. Dismissed recurring candidates are excluded.

## 4. Application flow

`Transaction → AnomalyService.purchase_rows() → eligible_purchases() → score_purchases()/detect_signals() → MultiSignalAnomalyService → /analytics/behavioral-alerts → BehavioralAlertsPanel`. Stable alert IDs hash method version, signal, account, currency, entity, and period. Reviews survive refreshes in the additive `005_behavioral_alert_reviews` migration. The old `/analytics/anomalies` endpoint and its transaction reviews remain available. The new UI shows period, baseline, explanation, and supporting transaction links.

## 5. Evaluation

Run `python -m evals.multi_signal_benchmark`. The fixed synthetic dataset has 76 eligible purchases and independently described amount, frequency, drift, and recurring-price scenarios. On the current code it produced 4 true positives, 0 false positives, precision 1.0, recall 1.0, F1 1.0, precision@4 1.0, and 0 false alerts per 100 eligible purchases. Runtime was about 2 ms locally and varies by machine. These deliberately simple cases are regression checks, not real-world accuracy. The pre-existing `python -m evals.anomaly_benchmark` compares amount ranking with offline Isolation Forest on synthetic data. It is not deployed. There are no independently reviewed real anomaly labels available to validate precision in production.

`backend/tests/test_multi_signal_anomalies.py` covers completed versus partial weeks, sparse entities, sustained drift, recurring price, account/currency isolation, and pending exclusion. Existing amount and recurrence tests guard old behavior. The local PostgreSQL connection was unavailable, so the new review migration and API persistence were not exercised against a live database in this workspace.

## 6. Tradeoffs and interpretation

The signals have different grains and thresholds, so their scores cannot be ranked as calibrated probabilities. Decimal amounts remain exact; no cross-currency summation occurs. We use statistics because limited independent labels cannot support a validated supervised model. Eight-week baselines are easy to inspect but can miss seasonality. Posted-date backfills and later categorization changes can alter historical replays. Expected/Unexpected reviews describe user expectations, not whether a statistical change exists, and are not automatically treated as training labels.

## 7. Next experiments

Collect enough voluntary, independent review outcomes to measure false-alert burden; compare rolling median with EWMA on seasonal and irregular synthetic series; add ingestion-time snapshots for true point-in-time evaluation; and test account-specific baseline coverage. A future price detector should distinguish variable utilities from stable subscriptions with more nuanced series models.

## 8. Interview preparation

1. **Why use MAD?** It measures typical deviation around the median and resists isolated extreme charges.
2. **Why include zero-count weeks?** Omitting them inflates the baseline for sporadic merchants and distorts frequency changes.
3. **How is temporal leakage prevented?** Amount history uses earlier posted dates; weekly features use only earlier completed weeks.
4. **Why are scores not probabilities?** No calibrated distribution or independent real-world labels justify probabilistic interpretation.
5. **Why keep Isolation Forest offline?** A synthetic benchmark alone cannot establish useful precision or alert burden on real behavior.
