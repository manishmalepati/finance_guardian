$ErrorActionPreference = 'Stop'
$baseUrl = 'http://localhost:8100'

$health = Invoke-RestMethod "$baseUrl/health"
$transactions = Invoke-RestMethod "$baseUrl/transactions"
$demoTransaction = $transactions | Where-Object { $_.description -eq 'DOORDASH DEMO' } | Select-Object -First 1
if (-not $demoTransaction) { throw 'Synthetic demo transaction was not found.' }
if ($demoTransaction.receipt_status -ne 'matched') { throw 'Synthetic receipt was not matched.' }

$context = Invoke-RestMethod "$baseUrl/transactions/$($demoTransaction.id)/context"
if ($context.matches.Count -ne 1) { throw 'Expected exactly one linked demo order.' }
if ($context.matches[0].order.items.Count -ne 2) { throw 'Demo order itemization is incomplete.' }
if ([decimal]$context.matches[0].order.total -ne 27) { throw 'Demo order total is incorrect.' }

$uberTransaction = $transactions | Where-Object { $_.description -eq 'UBER EATS DEMO' } | Select-Object -First 1
if (-not $uberTransaction -or $uberTransaction.receipt_status -ne 'matched') {
    throw 'Synthetic Uber Eats transaction and receipt match were not found.'
}
$uberContext = Invoke-RestMethod "$baseUrl/transactions/$($uberTransaction.id)/context"
if ($uberContext.matches.Count -ne 1 -or $uberContext.matches[0].order.items.Count -ne 2) {
    throw 'Synthetic Uber Eats itemization or match is incomplete.'
}
if ([decimal]$uberContext.matches[0].order.total -ne 19.50) {
    throw 'Synthetic Uber Eats order total is incorrect.'
}

$report = Invoke-RestMethod "$baseUrl/analytics/spending-report?start_date=2026-10-01&end_date=2026-10-31"
if ([decimal]$report.summary.posted_spending -ne 46.50) {
    throw 'Spending report does not equal the bank charge; check for receipt double counting.'
}

$connections = @(Invoke-RestMethod "$baseUrl/gmail/status")
if (-not ($connections | Where-Object { $_.status -eq 'demo' -and $_.source_count -eq 2 })) {
    throw 'Synthetic receipt source is missing.'
}

$goals = Invoke-RestMethod "$baseUrl/goals/evaluations?month=2026-10"
$parentGoal = $goals | Where-Object { $_.goal.category_id -eq 'food_dining' } | Select-Object -First 1
$childGoal = $goals | Where-Object { $_.goal.category_id -eq 'food_prepared' } | Select-Object -First 1
if (-not $parentGoal -or -not $childGoal) { throw 'Synthetic parent and subcategory goals are missing.' }
if ([decimal]$parentGoal.posted_spend -ne 46.50 -or [decimal]$childGoal.posted_spend -ne 46.50) {
    throw 'Goal progress did not follow the canonical transactions.'
}
if ([decimal]$parentGoal.over_amount -ne 11.50 -or [decimal]$childGoal.over_amount -ne 0) {
    throw 'Goal threshold and overage calculations are incorrect.'
}
if ($parentGoal.evidence.Count -ne 2 -or $childGoal.evidence.Count -ne 2) {
    throw 'Goal evidence did not identify both synthetic charges.'
}

Write-Output 'Demo smoke checks passed: receipts, matches, itemization, ledger total, and monthly category/subcategory goals.'
