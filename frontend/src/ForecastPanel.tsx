import { useCallback, useEffect, useState } from "react";
import { TrendingUp } from "lucide-react";

type CategoryOption = { id: string; name: string };
type Forecast = {
  month: string; currency: string; method: string; confidence: string;
  observed_to_date: string; forecast_remaining: string | null; forecast_total: string | null;
  lower_bound: string | null; upper_bound: string | null;
  historical_complete_months: number; budget: string | null; budget_status: string | null;
  forecast_overshoot: string | null; limitations: string[];
  category_breakdown?: { category_id: string; observed_to_date: string; forecast_total: string | null;
    confidence: string; method: string }[];
  confirmed_upcoming_recurring?: { series_key: string; merchant: string; next_expected_date: string;
    typical_amount: string; currency: string }[];
  recurring_policy?: string;
  backtest: { metrics: Record<string, { cases: number; mae: string; wape: number | null;
    interval_coverage: number | null; comparison_cases: number }> };
};

const localDay = () => {
  const day = new Date();
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
};
const money = (value: string | null, currency: string) => value === null ? "—" :
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(value));

export function ForecastPanel({ apiBaseUrl, accountId, categories }: {
  apiBaseUrl: string; accountId: string; categories: CategoryOption[];
}) {
  const [asOf, setAsOf] = useState(localDay);
  const [categoryId, setCategoryId] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [result, setResult] = useState<Forecast | null>(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    const query = new URLSearchParams({ as_of: asOf, currency });
    if (accountId) query.set("account_id", accountId);
    if (categoryId) query.set("category_id", categoryId);
    try {
      const response = await fetch(`${apiBaseUrl}/analytics/spending-forecast?${query}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not load the forecast.");
      setResult(body as Forecast); setError("");
    } catch (cause) {
      setResult(null); setError(cause instanceof Error ? cause.message : "Could not load the forecast.");
    }
  }, [accountId, apiBaseUrl, asOf, categoryId, currency]);
  useEffect(() => { void refresh(); }, [refresh]);
  const names = new Map(categories.map((item) => [item.id, item.name]));
  return <section className="surface anomalyPanel">
    <div className="sectionTitle"><div><span className="eyebrow">PREDICTIVE INSIGHTS</span><h2>Month-end spending forecast</h2></div><TrendingUp size={23} /></div>
    <p className="sectionDescription">A projection of gross settled purchases in one currency. It is an estimate, and historical categories may have changed since earlier months.</p>
    <div className="anomalyToolbar">
      <label>As of<input type="date" value={asOf} max={localDay()} onChange={(event) => setAsOf(event.target.value)} /></label>
      <label>Category<select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}><option value="">All categories</option>{categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Currency<input value={currency} maxLength={3} aria-label="Forecast currency" onChange={(event) => setCurrency(event.target.value.toUpperCase())} /></label>
    </div>
    {error && <p className="explainError" role="alert">{error}</p>}
    {result && <>
      {result.forecast_total === null ? <div className="recurringEmpty"><strong>Not enough reliable history</strong><p>{result.limitations[0]}</p></div> : <>
        <div className="anomalyGrid">
          <article className="anomalyCard"><span className="recurringCadence">Observed through {asOf}</span><h3>{money(result.observed_to_date, result.currency)}</h3><p className="anomalyContext">Settled purchases already posted this month.</p></article>
          <article className="anomalyCard"><span className="recurringCadence">Estimated remaining</span><h3>{money(result.forecast_remaining, result.currency)}</h3><p className="anomalyContext">{result.method.replace(/_/g, " ")} · {result.confidence}</p></article>
          <article className="anomalyCard"><span className="recurringCadence">Expected month-end</span><h3>{money(result.forecast_total, result.currency)}</h3><p className="anomalyContext">{result.lower_bound && result.upper_bound ? `Historical-error range ${money(result.lower_bound, result.currency)}–${money(result.upper_bound, result.currency)}` : "No defensible range yet; more history is needed."}</p></article>
        </div>
        {result.budget && <p className="anomalyContext">Monthly goal {money(result.budget, result.currency)} · {result.budget_status?.replace(/_/g, " ")}{result.forecast_overshoot && Number(result.forecast_overshoot) > 0 ? ` · projected overshoot ${money(result.forecast_overshoot, result.currency)}` : ""}. This is a status indicator, not an exceedance probability.</p>}
        {result.category_breakdown && <details className="recurringEvidence"><summary>Category projections</summary><div>{result.category_breakdown.map((item) => <p key={item.category_id}>{names.get(item.category_id) ?? item.category_id}: {money(item.observed_to_date, result.currency)} observed → {money(item.forecast_total, result.currency)} projected ({item.confidence})</p>)}</div></details>}
        {result.confirmed_upcoming_recurring && result.confirmed_upcoming_recurring.length > 0 && <details className="recurringEvidence"><summary>Confirmed upcoming recurring charges</summary><div>{result.confirmed_upcoming_recurring.map((item) => <p key={item.series_key}>{item.merchant}: {money(item.typical_amount, item.currency)} near {item.next_expected_date}</p>)}<p>{result.recurring_policy}</p></div></details>}
        <details className="recurringEvidence"><summary>Method and historical evaluation</summary><div><p>{result.historical_complete_months} completed historical months available.</p>{Object.entries(result.backtest.metrics).map(([method, metric]) => <p key={method}>{method.replace(/_/g, " ")}: {metric.cases} walk-forward cases, mean absolute error {money(metric.mae, result.currency)}{metric.interval_coverage === null ? "" : `, historical interval coverage ${Math.round(metric.interval_coverage * 100)}%`}</p>)}{result.limitations.map((item) => <p key={item}>{item}</p>)}</div></details>
      </>}
    </>}
  </section>;
}
