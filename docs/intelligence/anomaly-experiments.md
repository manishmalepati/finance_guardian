# Multi-signal anomaly experiments

Run from the repository root with the backend environment installed:

```powershell
.\.venv\Scripts\python.exe -m evals.multi_signal_benchmark
.\.venv\Scripts\python.exe -m evals.anomaly_benchmark
```

`multi_signal_benchmark` creates deterministic synthetic rows with four scenario labels set separately from detector code: an amount spike, a weekly purchase burst, a sustained category increase, and a recurring bill increase. It also includes a normal large purchase and a pending duplicate. It reports precision, recall, F1, precision@K, false alerts per 100 eligible purchases, runtime, misses, and false positives. On 2026-10-28 the current code returned 4/4 true positives from 76 eligible purchases, with no false positives. This is a small regression scenario suite, not a representative performance estimate. The earlier amount/Isolation Forest benchmark remains separate because its transaction-level observation population is different from completed-week signals.

The frequency rule uses eight earlier completed weeks. The drift rule uses eight reference weeks and a three-week confirmation. There is no model training step for these served methods; the offline Isolation Forest is fitted only on the chronological training portion of its separate synthetic dataset. A future evaluation should add seasonal and irregular spending populations, report delay by drift episode, compare matching alert budgets, and use independent human reviews before deployment decisions change.
