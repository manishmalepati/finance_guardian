import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, Check, RotateCcw, SearchCheck } from "lucide-react";

type Alert = {
  transaction_id: string; posted_date: string; merchant: string; account_id: string | null;
  currency: string; amount: string; typical_amount: string; amount_above_typical: string;
  score: number; reference_kind: string; reference_count: number;
  reference_transaction_ids: string[]; reason: string;
  review: "unreviewed" | "expected" | "unexpected";
};
type Result = { alert_count: number; eligible_purchase_count: number; reviewed_alert_count: number; alerts: Alert[] };

const localDay = (offset = 0) => {
  const day = new Date();
  day.setDate(day.getDate() + offset);
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
};
const money = (value: string, currency: string) => {
  try { return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(value)); }
  catch { return `${currency} ${value}`; }
};

export function AnomalyPanel({ apiBaseUrl, accountId, onTransaction }: {
  apiBaseUrl: string; accountId: string; onTransaction: (id: string) => void;
}) {
  const [startDate, setStartDate] = useState(() => localDay(-90));
  const [endDate, setEndDate] = useState(localDay);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [showExpected, setShowExpected] = useState(false);
  const refresh = useCallback(async () => {
    const query = new URLSearchParams({ start_date: startDate, end_date: endDate, currency: "USD" });
    if (accountId) query.set("account_id", accountId);
    try {
      const response = await fetch(`${apiBaseUrl}/analytics/anomalies?${query}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not load unusual charges.");
      setResult(body as Result); setError("");
    } catch (cause) {
      setResult(null); setError(cause instanceof Error ? cause.message : "Could not load unusual charges.");
    }
  }, [accountId, apiBaseUrl, startDate, endDate]);
  useEffect(() => { void refresh(); }, [refresh]);

  const review = async (id: string, decision: Alert["review"]) => {
    setBusy(id);
    try {
      const response = await fetch(`${apiBaseUrl}/analytics/anomalies/${id}/review`, {
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
  const visible = useMemo(() => (result?.alerts ?? []).filter((item) => showExpected || item.review !== "expected"), [result, showExpected]);
  const expectedCount = (result?.alerts ?? []).filter((item) => item.review === "expected").length;

  return <section className="surface anomalyPanel">
    <div className="sectionTitle"><div><span className="eyebrow">UNUSUAL CHARGES</span><h2>Charges worth a second look</h2></div><SearchCheck size={23} /></div>
    <p className="sectionDescription">Ranked by how far a settled charge exceeds earlier purchases. This is a spending pattern, not a fraud finding or probability.</p>
    <div className="anomalyToolbar"><label>From<input type="date" max={endDate} value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label>To<input type="date" min={startDate} max={localDay()} value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label><span>{result ? `${result.alert_count} flags from ${result.eligible_purchase_count} eligible purchases` : "Checking settled purchases"}</span>{expectedCount > 0 && <label className="anomalyToggle"><input type="checkbox" checked={showExpected} onChange={(event) => setShowExpected(event.target.checked)} />Show {expectedCount} marked expected</label>}</div>
    {error && <p className="explainError" role="alert">{error}</p>}
    {result && visible.length === 0 && <div className="recurringEmpty"><strong>No visible unusual charges</strong><p>A merchant needs five earlier purchases, or a category needs twelve, before a charge can be compared. Marked expected charges can be shown above.</p></div>}
    <div className="anomalyGrid">{visible.map((item) => <article className={`anomalyCard ${item.review}`} key={item.transaction_id}>
      <div className="anomalyCardHead"><div><span className="recurringCadence">{item.posted_date} · {item.reference_kind} history</span><h3>{item.merchant}</h3></div><strong>{money(item.amount, item.currency)}</strong></div>
      <p className="anomalyDifference">{money(item.amount_above_typical, item.currency)} above the earlier typical {money(item.typical_amount, item.currency)}</p>
      <p className="anomalyContext">{item.reason} Based on {item.reference_count} earlier settled purchases in this account and currency.</p>
      <details className="recurringEvidence"><summary>Review supporting transactions</summary><div><button onClick={() => onTransaction(item.transaction_id)}>Current charge <ArrowRight size={12} /></button>{item.reference_transaction_ids.map((id) => <button key={id} onClick={() => onTransaction(id)}>Earlier {id.slice(0, 8)} <ArrowRight size={12} /></button>)}</div></details>
      <div className="recurringActions">{item.review !== "unexpected" && <button className="secondaryButton" onClick={() => void review(item.transaction_id, "unexpected")} disabled={Boolean(busy)}><SearchCheck size={14} />Unexpected</button>}{item.review !== "expected" && <button className="textButton" onClick={() => void review(item.transaction_id, "expected")} disabled={Boolean(busy)}><Check size={14} />Expected</button>}{item.review !== "unreviewed" && <button className="textButton" onClick={() => void review(item.transaction_id, "unreviewed")} disabled={Boolean(busy)}><RotateCcw size={14} />Undo</button>}</div>
      {item.review !== "unreviewed" && <span className="recurringReviewed">Marked {item.review} by you</span>}
    </article>)}</div>
  </section>;
}
