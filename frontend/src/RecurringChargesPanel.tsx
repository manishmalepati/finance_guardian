import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, CalendarClock, Check, RotateCcw, X } from "lucide-react";

type Candidate = {
  series_key: string; merchant: string; account_id: string | null; currency: string;
  cadence: "weekly" | "biweekly" | "monthly" | "yearly";
  confidence: "high" | "medium" | "low";
  transaction_count: number; distinct_dates: number;
  matching_intervals: number; observed_intervals: number;
  typical_amount: string; observed_low: string; observed_high: string;
  latest_increase_vs_previous: string | null;
  last_date: string; next_expected_date: string; timing: "upcoming" | "overdue";
  transaction_ids: string[]; reason: string;
  review: "unreviewed" | "confirmed" | "not_recurring";
};
type CandidateResponse = {
  as_of: string; candidate_count: number; eligible_purchase_count: number;
  merchant_account_groups: number; excluded_counts: Record<string, number>;
  candidates: Candidate[];
};

const localToday = () => {
  const today = new Date();
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
};
const money = (amount: string, currency: string) => {
  try { return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(amount)); }
  catch { return `${currency} ${amount}`; }
};
const prettyDate = (value: string) => new Intl.DateTimeFormat("en-US", {
  month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
}).format(new Date(`${value}T00:00:00Z`));

export function RecurringChargesPanel({ apiBaseUrl, accountId, accountNames, onTransaction }: {
  apiBaseUrl: string; accountId: string; accountNames: Map<string, string>;
  onTransaction: (id: string) => void;
}) {
  const [asOf, setAsOf] = useState(localToday);
  const [result, setResult] = useState<CandidateResponse | null>(null);
  const [error, setError] = useState("");
  const [busyKey, setBusyKey] = useState("");
  const [showDismissed, setShowDismissed] = useState(false);

  const refresh = useCallback(async () => {
    const query = new URLSearchParams({ as_of: asOf });
    if (accountId) query.set("account_id", accountId);
    try {
      const response = await fetch(`${apiBaseUrl}/analytics/recurring-charges?${query}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not load recurring charges.");
      setResult(body as CandidateResponse);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load recurring charges.");
      setResult(null);
    }
  }, [accountId, apiBaseUrl, asOf]);

  useEffect(() => { void refresh(); }, [refresh]);

  const review = async (seriesKey: string, decision: Candidate["review"]) => {
    setBusyKey(seriesKey);
    try {
      const response = await fetch(`${apiBaseUrl}/analytics/recurring-charges/${seriesKey}/review`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, as_of: asOf }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not save your review.");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save your review.");
    } finally { setBusyKey(""); }
  };

  const visible = useMemo(() => (result?.candidates ?? []).filter((item) =>
    showDismissed || item.review !== "not_recurring"), [result, showDismissed]);
  const dismissedCount = (result?.candidates ?? []).filter((item) => item.review === "not_recurring").length;

  return <section className="surface recurringPanel">
    <div className="sectionTitle"><div><span className="eyebrow">POSSIBLE RECURRING CHARGES</span><h2>Payments that follow a pattern</h2></div><CalendarClock size={23} /></div>
    <p className="sectionDescription">These are timing and amount patterns, not confirmed subscriptions. Next dates are estimates based on posted history.</p>
    <div className="recurringToolbar"><label>As of<input type="date" max={localToday()} value={asOf} onChange={(event) => setAsOf(event.target.value)} /></label><span>{result ? `${result.candidate_count} candidates from ${result.eligible_purchase_count} settled purchases` : "Checking purchase history"}</span>{dismissedCount > 0 && <label className="recurringToggle"><input type="checkbox" checked={showDismissed} onChange={(event) => setShowDismissed(event.target.checked)} />Show {dismissedCount} dismissed</label>}</div>
    {error && <p className="explainError" role="alert">{error}</p>}
    {result && visible.length === 0 && <div className="recurringEmpty"><strong>No visible recurring-charge candidates</strong><p>Three or more suitably timed purchases with reasonably stable amounts are needed. Dismissed patterns can be shown above.</p></div>}
    <div className="recurringGrid">{visible.map((item) => <article className={`recurringCard ${item.review}`} key={item.series_key}>
      <div className="recurringCardTop"><div><span className="recurringCadence">{item.cadence} · {item.confidence} signal</span><h3>{item.merchant}</h3><small>{item.account_id ? accountNames.get(item.account_id) ?? "Connected account" : "Unlinked account"}</small></div><span className={`recurringTiming ${item.timing}`}>{item.timing === "overdue" ? "Expected date passed" : "Upcoming estimate"}</span></div>
      <div className="recurringNext"><span>Next expected date</span><strong>{prettyDate(item.next_expected_date)}</strong><small>Typical amount {money(item.typical_amount, item.currency)}</small></div>
      <div className="recurringFacts"><span>{item.transaction_count} charges on {item.distinct_dates} dates</span><span>Observed {money(item.observed_low, item.currency)}–{money(item.observed_high, item.currency)}</span></div>
      {item.latest_increase_vs_previous && <p className="recurringIncrease">Latest charge was {money(item.latest_increase_vs_previous, item.currency)} above the earlier typical amount.</p>}
      <details className="recurringEvidence"><summary>Why this was flagged · view transactions</summary><p>{item.reason} Last posted charge: {prettyDate(item.last_date)}.</p><div>{item.transaction_ids.map((id) => <button key={id} onClick={() => onTransaction(id)} title={`Open transaction ${id}`}>{id.slice(0, 8)} <ArrowRight size={12} /></button>)}</div></details>
      <div className="recurringActions">
        {item.review !== "confirmed" && <button className="secondaryButton" onClick={() => void review(item.series_key, "confirmed")} disabled={Boolean(busyKey)}><Check size={14} />Confirm recurring</button>}
        {item.review !== "not_recurring" && <button className="textButton" onClick={() => void review(item.series_key, "not_recurring")} disabled={Boolean(busyKey)}><X size={14} />Not recurring</button>}
        {item.review !== "unreviewed" && <button className="textButton" onClick={() => void review(item.series_key, "unreviewed")} disabled={Boolean(busyKey)}><RotateCcw size={14} />Undo review</button>}
      </div>
      {item.review === "confirmed" && <span className="recurringReviewed">Confirmed by you</span>}
      {item.review === "not_recurring" && <span className="recurringReviewed">Dismissed by you</span>}
    </article>)}</div>
  </section>;
}
