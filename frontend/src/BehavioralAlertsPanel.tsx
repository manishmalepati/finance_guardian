import { useCallback, useEffect, useState } from "react";
import { Activity, ArrowRight, Check, RotateCcw } from "lucide-react";

type Alert = {
  alert_id: string; signal_type: "frequency" | "drift" | "recurring_price" | "amount";
  entity_type: string; entity_id: string; account_id: string | null; currency: string;
  period_start: string; period_end: string; observed_value: string; baseline_value: string;
  supporting_transaction_ids: string[]; explanation: string;
  review: "unreviewed" | "expected" | "unexpected";
};
type Result = { alerts: Alert[]; eligible_purchase_count: number; alert_count: number };

const localDay = (offset = 0) => {
  const day = new Date();
  day.setDate(day.getDate() + offset);
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
};
const names: Record<Alert["signal_type"], string> = {
  amount: "Unusual amount", frequency: "Purchase frequency",
  drift: "Sustained spending increase", recurring_price: "Recurring price change",
};

export function BehavioralAlertsPanel({ apiBaseUrl, accountId, onTransaction }: {
  apiBaseUrl: string; accountId: string; onTransaction: (id: string) => void;
}) {
  const [startDate, setStartDate] = useState(() => localDay(-90));
  const [endDate, setEndDate] = useState(localDay);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const refresh = useCallback(async () => {
    const query = new URLSearchParams({ start_date: startDate, end_date: endDate, currency: "USD" });
    if (accountId) query.set("account_id", accountId);
    try {
      const response = await fetch(`${apiBaseUrl}/analytics/behavioral-alerts?${query}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not load behavioral alerts.");
      setResult(body as Result); setError("");
    } catch (cause) {
      setResult(null); setError(cause instanceof Error ? cause.message : "Could not load behavioral alerts.");
    }
  }, [accountId, apiBaseUrl, startDate, endDate]);
  useEffect(() => { void refresh(); }, [refresh]);

  const review = async (id: string, decision: Alert["review"]) => {
    setBusy(id);
    try {
      const response = await fetch(`${apiBaseUrl}/analytics/behavioral-alerts/${id}/review`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, start_date: startDate, end_date: endDate,
                               currency: "USD", account_id: accountId || null }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not save your review.");
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save your review."); }
    finally { setBusy(""); }
  };
  const alerts = (result?.alerts ?? []).filter((item) => item.signal_type !== "amount");
  return <section className="surface anomalyPanel">
    <div className="sectionTitle"><div><span className="eyebrow">BEHAVIORAL PATTERNS</span><h2>Changes in how you spend</h2></div><Activity size={23} /></div>
    <p className="sectionDescription">Completed weeks reveal purchase bursts and sustained increases. Recurring price changes are candidates for review. These are statistical signals, not fraud findings.</p>
    <div className="anomalyToolbar"><label>From<input type="date" max={endDate} value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label>To<input type="date" min={startDate} max={localDay()} value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label><span>{result ? `${alerts.length} patterns from ${result.eligible_purchase_count} eligible purchases` : "Checking completed periods"}</span></div>
    {error && <p className="explainError" role="alert">{error}</p>}
    {result && alerts.length === 0 && <div className="recurringEmpty"><strong>No behavioral changes detected</strong><p>Weekly patterns need enough completed historical weeks. A quiet result does not prove spending is normal.</p></div>}
    <div className="anomalyGrid">{alerts.map((item) => <article className={`anomalyCard ${item.review}`} key={item.alert_id}>
      <div className="anomalyCardHead"><div><span className="recurringCadence">{names[item.signal_type]} · {item.period_start} to {item.period_end}</span><h3>{item.entity_type === "recurring_series" ? "Recurring payment" : item.entity_id}</h3></div></div>
      <p className="anomalyContext">{item.explanation}</p>
      <p className="anomalyDifference">Observed {item.observed_value} · Earlier baseline {item.baseline_value} {item.signal_type !== "frequency" && item.currency}</p>
      <details className="recurringEvidence"><summary>Review supporting transactions</summary><div>{item.supporting_transaction_ids.map((id) => <button key={id} onClick={() => onTransaction(id)}>{id.slice(0, 8)} <ArrowRight size={12} /></button>)}</div></details>
      <div className="recurringActions">{item.review !== "unexpected" && <button className="secondaryButton" onClick={() => void review(item.alert_id, "unexpected")} disabled={Boolean(busy)}><Activity size={14} />Unexpected</button>}{item.review !== "expected" && <button className="textButton" onClick={() => void review(item.alert_id, "expected")} disabled={Boolean(busy)}><Check size={14} />Expected</button>}{item.review !== "unreviewed" && <button className="textButton" onClick={() => void review(item.alert_id, "unreviewed")} disabled={Boolean(busy)}><RotateCcw size={14} />Undo</button>}</div>
      {item.review !== "unreviewed" && <span className="recurringReviewed">Marked {item.review} by you</span>}
    </article>)}</div>
  </section>;
}
