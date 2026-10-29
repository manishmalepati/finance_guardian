import { useState } from "react";
import type { FormEvent } from "react";
import { Bot, ArrowRight } from "lucide-react";

type Fact = { id: string; text: string; transaction_ids: string[]; link: string | null };
type Response = { answer: string; facts: Fact[]; evidence_transaction_ids: string[];
  tools_used: string[]; limitations: string[] };

const localDay = () => {
  const day = new Date();
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
};
const destinations: Record<string, string> = {
  forecast: "Forecast", "behavioral-alerts": "Behavioral alerts",
  "recurring-charges": "Recurring charges", intelligence: "Spending comparison",
};

export function InvestigatorPanel({ apiBaseUrl, accountId, onTransaction }: {
  apiBaseUrl: string; accountId: string; onTransaction: (id: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<Response | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const ask = async (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim()) return;
    setBusy(true); setError(""); setResult(null);
    try {
      const response = await fetch(`${apiBaseUrl}/agent/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question.trim(), account_id: accountId || null,
                               currency: "USD", as_of: localDay() }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "The investigation could not complete.");
      setResult(body as Response);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The investigation could not complete.");
    } finally { setBusy(false); }
  };
  return <section className="surface guardianPanel">
    <div className="sectionTitle"><div><span className="eyebrow">FINANCIAL INVESTIGATOR</span><h2>Ask about your spending</h2></div><Bot size={23} /></div>
    <p className="sectionDescription">Ask why spending changed, whether a goal looks at risk, or which patterns deserve review. Answers use verified finance calculations and show supporting activity. Requires a configured LLM provider.</p>
    <form className="searchBar" onSubmit={(event) => void ask(event)}><input value={question} maxLength={600} onChange={(event) => setQuestion(event.target.value)} placeholder="Why did my spending increase this month?" aria-label="Question for Financial Investigator" /><button className="primaryButton" type="submit" disabled={busy}>{busy ? "Investigating…" : "Investigate"}</button></form>
    {error && <p className="explainError" role="alert">{error}</p>}
    {result && <div className="guardianResult"><p className="guardianAnswer">{result.answer}</p>
      {result.facts.length > 0 && <div className="inlineActions">{[...new Set(result.facts.map((fact) => fact.link).filter((link): link is string => Boolean(link)))].map((link) => <a className="secondaryButton" key={link} href={`#${link}`}>{destinations[link] ?? "View analysis"} <ArrowRight size={14} /></a>)}</div>}
      {result.evidence_transaction_ids.length > 0 && <details className="recurringEvidence"><summary>Supporting transactions ({result.evidence_transaction_ids.length})</summary><div>{result.evidence_transaction_ids.map((id) => <button key={id} onClick={() => onTransaction(id)}>{id.slice(0, 8)} <ArrowRight size={12} /></button>)}</div></details>}
      {result.limitations.length > 0 && <p className="anomalyContext">{result.limitations.join(" ")}</p>}
      {result.tools_used.length > 0 && <details className="recurringEvidence"><summary>How this answer was checked</summary><p>{result.tools_used.map((name) => name.replace(/_/g, " ")).join(", ")}</p></details>}
    </div>}
  </section>;
}
