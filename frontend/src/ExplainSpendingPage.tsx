import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, CalendarRange, ChevronDown, RefreshCw } from "lucide-react";

type Period = { start: string; end: string; days: number };
type Driver = {
  id: string; name: string; category_id?: string;
  prior_total: string; current_total: string; delta: string;
  prior_count: number; current_count: number;
  prior_average: string | null; current_average: string | null;
  frequency_effect: string; average_amount_effect: string;
  change_kind: "continuing" | "new" | "vanished";
  prior_transaction_ids: string[]; current_transaction_ids: string[];
};
type Explanation = {
  prior_period: Period; current_period: Period; comparable_length: boolean;
  currency: string; prior_total: string; current_total: string; delta: string;
  prior_count: number; current_count: number;
  categories: Driver[]; merchants: Driver[];
  reconciliation_difference: string;
  excluded_counts: Record<string, number>; refund_policy: string;
};

const monthRange = (month: string) => {
  const [year, number] = month.split("-").map(Number);
  return { start: `${month}-01`, end: `${month}-${String(new Date(year, number, 0).getDate()).padStart(2, "0")}` };
};
const previousMonth = (offset: number) => {
  const now = new Date();
  const first = new Date(now.getFullYear(), now.getMonth() - offset, 1);
  return `${first.getFullYear()}-${String(first.getMonth() + 1).padStart(2, "0")}`;
};
const initialPrior = monthRange(previousMonth(2));
const initialCurrent = monthRange(previousMonth(1));
const formatMoney = (value: string | number, currency: string) => new Intl.NumberFormat("en-US", {
  style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 2,
}).format(Number(value));
const signedMoney = (value: string, currency: string) =>
  `${Number(value) > 0 ? "+" : Number(value) < 0 ? "−" : ""}${formatMoney(Math.abs(Number(value)), currency)}`;

function DriverRows({ rows, currency, onTransaction, categoryNames }: {
  rows: Driver[]; currency: string; onTransaction: (id: string) => void;
  categoryNames?: Map<string, string>;
}) {
  const largest = Math.max(1, ...rows.map((row) => Math.abs(Number(row.delta))));
  if (rows.length === 0) return <p className="explainEmpty">No settled purchases in these periods.</p>;
  return <div className="explainDrivers">{rows.map((row) => {
    const delta = Number(row.delta);
    return <details className="explainDriver" key={row.id}>
      <summary>
        <span className="explainDriverName"><strong>{row.name}</strong>{categoryNames && <small>{categoryNames.get(row.category_id ?? "") ?? "Uncategorized"}</small>}</span>
        <span className="explainDriverTrack"><span className={delta >= 0 ? "up" : "down"} style={{ width: `${Math.max(2, Math.abs(delta) / largest * 100)}%` }} /></span>
        <strong className={delta >= 0 ? "explainUp" : "explainDown"}>{signedMoney(row.delta, currency)}</strong>
        <ChevronDown size={15} className="explainChevron" />
      </summary>
      <div className="explainDriverDetail">
        <div className="explainDriverFacts">
          <span>Earlier<strong>{formatMoney(row.prior_total, currency)} · {row.prior_count} purchases</strong></span>
          <span>Later<strong>{formatMoney(row.current_total, currency)} · {row.current_count} purchases</strong></span>
          <span>Purchase count effect<strong>{signedMoney(row.frequency_effect, currency)}</strong></span>
          <span>Average amount effect<strong>{signedMoney(row.average_amount_effect, currency)}</strong></span>
        </div>
        <p>{row.change_kind === "new" ? "New spending in the later period." : row.change_kind === "vanished" ? "Spending present only in the earlier period." : `Average purchase: ${formatMoney(row.prior_average ?? 0, currency)} → ${formatMoney(row.current_average ?? 0, currency)}.`}</p>
        <div className="explainEvidence">
          <span>Supporting transactions</span>
          <div>{row.prior_transaction_ids.map((id) => <button key={id} onClick={() => onTransaction(id)} title={`Open earlier transaction ${id}`}>Earlier {id.slice(0, 8)} <ArrowRight size={12} /></button>)}
            {row.current_transaction_ids.map((id) => <button key={id} onClick={() => onTransaction(id)} title={`Open later transaction ${id}`}>Later {id.slice(0, 8)} <ArrowRight size={12} /></button>)}</div>
        </div>
      </div>
    </details>;
  })}</div>;
}

export function ExplainSpendingPage({ apiBaseUrl, accountId, onTransaction }: {
  apiBaseUrl: string; accountId: string; onTransaction: (id: string) => void;
}) {
  const [priorStart, setPriorStart] = useState(initialPrior.start);
  const [priorEnd, setPriorEnd] = useState(initialPrior.end);
  const [currentStart, setCurrentStart] = useState(initialCurrent.start);
  const [currentEnd, setCurrentEnd] = useState(initialCurrent.end);
  const [result, setResult] = useState<Explanation | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState("");

  const compare = useCallback(async () => {
    if (priorStart > priorEnd || currentStart > currentEnd || priorEnd >= currentStart) {
      setError("Choose two chronological, nonoverlapping periods with valid start and end dates.");
      return;
    }
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ prior_start: priorStart, prior_end: priorEnd,
      current_start: currentStart, current_end: currentEnd, currency: "USD" });
    if (accountId) params.set("account_id", accountId);
    try {
      const response = await fetch(`${apiBaseUrl}/analytics/explain-spending?${params}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not compare spending.");
      setResult(body as Explanation);
      setCategoryFilter("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not compare spending.");
      setResult(null);
    } finally { setLoading(false); }
  }, [accountId, apiBaseUrl, priorStart, priorEnd, currentStart, currentEnd]);

  useEffect(() => { void compare(); }, [accountId]); // Refresh the visible account scope.
  const names = useMemo(() => new Map(result?.categories.map((row) => [row.id, row.name]) ?? []), [result]);
  const visibleMerchants = result?.merchants.filter((row) => !categoryFilter || row.category_id === categoryFilter) ?? [];
  const topDriver = result?.categories.find((row) => Number(row.delta) !== 0);

  return <div className="explainPage">
    <section className="surface explainIntro">
      <div className="sectionTitle"><div><span className="eyebrow">EXPLAIN MY SPENDING</span><h2>What changed between periods?</h2></div><CalendarRange size={23} /></div>
      <p className="sectionDescription">Compare settled purchase spending. Every category and merchant contribution adds up to the exact change.</p>
      <div className="explainPeriodGrid">
        <fieldset><legend>Earlier period</legend><label>From<input type="date" value={priorStart} onChange={(event) => setPriorStart(event.target.value)} /></label><label>To<input type="date" value={priorEnd} onChange={(event) => setPriorEnd(event.target.value)} /></label></fieldset>
        <fieldset><legend>Later period</legend><label>From<input type="date" value={currentStart} onChange={(event) => setCurrentStart(event.target.value)} /></label><label>To<input type="date" value={currentEnd} onChange={(event) => setCurrentEnd(event.target.value)} /></label></fieldset>
        <button className="primaryButton" onClick={() => void compare()} disabled={loading}>{loading ? <RefreshCw size={15} className="spinning" /> : <ArrowRight size={15} />}Compare</button>
      </div>
      {error && <p className="explainError" role="alert">{error}</p>}
    </section>
    {result && <>
      <div className="explainSummary">
        <article><span>Earlier spending</span><strong>{formatMoney(result.prior_total, result.currency)}</strong><small>{result.prior_count} purchases</small></article>
        <article><span>Later spending</span><strong>{formatMoney(result.current_total, result.currency)}</strong><small>{result.current_count} purchases</small></article>
        <article className="explainChange"><span>Change</span><strong className={Number(result.delta) >= 0 ? "explainUp" : "explainDown"}>{signedMoney(result.delta, result.currency)}</strong><small>{result.reconciliation_difference === "0.00" ? "All contributions reconciled" : "Review reconciliation"}</small></article>
      </div>
      {topDriver && <section className="explainInsight"><span>Largest category shift</span><strong>{topDriver.name}: {signedMoney(topDriver.delta, result.currency)}</strong><p>This describes recorded purchase changes; it does not infer why you made them.</p></section>}
      {!result.comparable_length && <p className="explainCaution">These periods have different lengths ({result.prior_period.days} and {result.current_period.days} days), so their pace is not directly comparable.</p>}
      <div className="explainColumns">
        <section className="surface"><div className="sectionTitle"><div><span className="eyebrow">CATEGORY DRIVERS</span><h2>Where the change happened</h2></div></div><p className="sectionDescription">Increases and offsets are both included.</p><DriverRows rows={result.categories} currency={result.currency} onTransaction={onTransaction} /></section>
        <section className="surface"><div className="sectionTitle"><div><span className="eyebrow">MERCHANT DRIVERS</span><h2>Purchase frequency and size</h2></div></div><label className="explainFilter">Category<select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}><option value="">All categories</option>{result.categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label><DriverRows rows={visibleMerchants} currency={result.currency} onTransaction={onTransaction} categoryNames={names} /></section>
      </div>
      <section className="surface explainMethod"><span className="eyebrow">HOW THIS IS CALCULATED</span><p>Settled debit purchases in {result.currency}, excluding known transfers and card payments. {result.refund_policy} Transaction count effect uses the earlier average; the remaining change is the average amount effect. New and vanished groups use their full change as the count effect.</p><p>{Object.entries(result.excluded_counts).map(([key, count]) => `${key.replace(/_/g, " ")}: ${count}`).join(" · ") || "No excluded transactions in these periods."}</p></section>
    </>}
  </div>;
}
