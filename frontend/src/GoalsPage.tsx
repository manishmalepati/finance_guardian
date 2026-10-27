import { Fragment, useState } from "react";
import type { FormEvent } from "react";
import { CategoryFillTile } from "./CategoryFillTile";
import type { GoalCategory, GoalEvaluation } from "./goalTypes";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const currencyMoney = (amount: number, currency: string) => new Intl.NumberFormat("en-US", {
  style: "currency", currency, minimumFractionDigits: 2,
}).format(amount);

export function GoalsPage({ evaluations, priorEvaluations, categories, month, onMonthChange, onRefresh, onTransaction }: {
  evaluations: GoalEvaluation[]; priorEvaluations: GoalEvaluation[]; categories: GoalCategory[]; month: string;
  onMonthChange: (month: string) => void; onRefresh: () => Promise<void>;
  onTransaction: (id: string) => void;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [categoryId, setCategoryId] = useState("");
  const [name, setName] = useState("");
  const [threshold, setThreshold] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const eligibleCategories = categories.filter((category) => !["income", "financial"].includes(category.category_id));

  const reset = () => {
    setEditingId(null); setCategoryId(""); setName(""); setThreshold("");
    setCurrency("USD"); setTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  };
  const startEdit = (entry: GoalEvaluation) => {
    setEditingId(entry.goal.id); setCategoryId(entry.goal.category_id);
    setName(entry.goal.name); setThreshold(entry.goal.threshold_amount);
    setCurrency(entry.goal.currency); setTimezone(entry.goal.timezone);
    document.getElementById("goal-form")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const request = async (url: string, method: string, payload?: object) => {
    const response = await fetch(`${API_BASE_URL}${url}`, {
      method, headers: payload ? { "Content-Type": "application/json" } : undefined,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail ?? "Could not save the goal.");
    }
  };
  const perform = async (action: () => Promise<void>, success: string) => {
    setBusy(true); setMessage("");
    try { await action(); await onRefresh(); setMessage(success); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Goal action failed."); }
    finally { setBusy(false); }
  };
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (!categoryId || !threshold) return;
    void perform(async () => {
      const selected = eligibleCategories.flatMap((category) => [category, ...category.subcategories])
        .find((category) => category.category_id === categoryId);
      const payload = { category_id: categoryId,
        name: name.trim() || (editingId ? `${selected?.display_name ?? "Category"} monthly goal` : undefined),
        threshold_amount: threshold, currency, timezone };
      await request(editingId ? `/goals/${editingId}` : "/goals", editingId ? "PATCH" : "POST", payload);
      reset();
    }, editingId ? "Goal updated." : "Monthly goal created.");
  };
  const toggle = (entry: GoalEvaluation) => void perform(async () => {
    await request(`/goals/${entry.goal.id}`, "PATCH", {
      status: entry.goal.status === "active" ? "paused" : "active",
    });
  }, entry.goal.status === "active" ? "Goal paused." : "Goal resumed.");
  const remove = (entry: GoalEvaluation) => {
    if (!window.confirm(`Remove the monthly goal for ${entry.goal.category_name}?`)) return;
    void perform(async () => {
      await request(`/goals/${entry.goal.id}`, "DELETE");
      if (editingId === entry.goal.id) reset();
    }, "Goal removed.");
  };

  return <>
    <div className="pageHeading"><div><div className="eyebrow">MONTHLY INTENTIONS</div><h1>Goals</h1><p>Set a cap for a category or subcategory and inspect every transaction behind its progress.</p></div>
      <label className="monthPicker"><span>Period</span><input type="month" value={month} onChange={(event) => onMonthChange(event.target.value)} aria-label="Goal month" /></label>
    </div>
    <section className="surface goalEditor" id="goal-form">
      <div className="sectionTitle"><div><span className="eyebrow">{editingId ? "EDIT TARGET" : "NEW TARGET"}</span><h2>{editingId ? "Edit monthly goal" : "Create a monthly goal"}</h2></div><span className="sectionHint">Category or subcategory</span></div>
      <p className="sectionDescription">Goals repeat each calendar month. Posted bank transactions count toward progress; pending activity is projected separately.</p>
      <form className="goalForm" onSubmit={save}>
        <label>Scope<select value={categoryId} onChange={(event) => setCategoryId(event.target.value)} required>
          <option value="">Choose a category or subcategory</option>
          {eligibleCategories.map((category) => <Fragment key={category.category_id}>
            <option value={category.category_id}>{category.display_name} · all subcategories</option>
            <optgroup label={category.display_name}>{category.subcategories.map((child) =>
              <option key={child.category_id} value={child.category_id}>{child.display_name}</option>)}</optgroup>
          </Fragment>)}
        </select></label>
        <label>Monthly cap<input type="number" min="0.01" step="0.01" value={threshold} onChange={(event) => setThreshold(event.target.value)} placeholder="0.00" required /></label>
        <label>Name<input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} placeholder="Optional label" /></label>
        <label>Currency<input value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} pattern="[A-Z]{3}" maxLength={3} required /></label>
        <label>Time zone<input value={timezone} onChange={(event) => setTimezone(event.target.value)} placeholder="America/Los_Angeles" required /></label>
        <div className="goalFormActions"><button className="primaryButton" type="submit" disabled={busy}>{editingId ? "Save changes" : "Create goal"}</button>
          {editingId && <button className="secondaryButton" type="button" onClick={reset}>Cancel edit</button>}</div>
      </form>
      {message && <p className="goalMessage" role="status">{message}</p>}
    </section>
    {evaluations.length === 0 ? <section className="surface goalEmpty"><strong>No monthly goals yet</strong><p>Choose a category above to make your first measurable goal. Existing category limits appear here automatically.</p></section>
      : <div className="goalGrid">{evaluations.map((entry) => {
        const goal = entry.goal;
        const active = goal.status === "active";
        const posted = Number(entry.posted_spend);
        const pending = Number(entry.pending_net);
        const prior = priorEvaluations.find((item) => item.goal_id === goal.id);
        return <article className={`surface goalCard${active ? "" : " goalPaused"}`} key={goal.id}>
          <div className="goalCardHead"><div><span className="eyebrow">{goal.scope_kind === "category" ? "CATEGORY GOAL" : "SUBCATEGORY GOAL"}</span><h2>{goal.name}</h2><p>{goal.category_name} · {goal.timezone}</p></div><span className={`goalStatus ${goal.status}`}>{goal.status}</span></div>
          <div className="goalCardBody"><CategoryFillTile name={goal.category_name} posted={posted} pending={pending}
            limit={Number(goal.threshold_amount)} currency={goal.currency} paused={!active} large />
            <div className="goalNumbers"><div><span>Posted net</span><strong>{currencyMoney(posted, goal.currency)}</strong></div>
              <div><span>Pending exposure</span><strong>{currencyMoney(pending, goal.currency)}</strong></div>
              <div><span>Monthly cap</span><strong>{currencyMoney(Number(goal.threshold_amount), goal.currency)}</strong></div>
              <div><span>Prior month, same rules</span><strong>{prior ? currencyMoney(Number(prior.posted_spend), goal.currency) : "Unavailable"}</strong></div>
              <div><span>Period</span><strong>{entry.period_start} – {entry.period_end}</strong></div></div>
          </div>
          <div className="goalActions"><button className="textButton" onClick={() => startEdit(entry)} disabled={busy}>Edit</button>
            <button className="textButton" onClick={() => toggle(entry)} disabled={busy}>{active ? "Pause" : "Resume"}</button>
            <button className="textButton dangerLink" onClick={() => remove(entry)} disabled={busy}>Remove</button></div>
          <details className="goalEvidence"><summary>Counted transactions ({entry.evidence.length})</summary>
            <p>Posted debits minus credits in this scope. Pending transactions affect only the projection.</p>
            {entry.evidence.length === 0 && <span>No qualifying transactions for this month.</span>}
            {entry.evidence.map((item) => <button className="goalEvidenceRow" key={item.transaction_id} onClick={() => onTransaction(item.transaction_id)}>
              <span><strong>{item.merchant}</strong><small>{item.posted_date}{item.pending ? " · pending" : ""}{item.direction === "credit" ? " · credit" : ""}</small></span>
              <strong>{item.direction === "credit" ? "−" : "+"}{currencyMoney(Number(item.amount), goal.currency)}</strong>
            </button>)}
            {(entry.exclusions.unknown_currency > 0 || entry.exclusions.other_currency > 0) &&
              <p>{entry.exclusions.unknown_currency} unknown currency and {entry.exclusions.other_currency} different currency transactions excluded.</p>}
            {entry.caveats.map((caveat) => <p key={caveat}>{caveat}</p>)}
          </details>
        </article>;
      })}</div>}
  </>;
}
