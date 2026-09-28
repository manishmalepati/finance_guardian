import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Bot, FileUp, RefreshCw, Search } from "lucide-react";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type Transaction = {
  id: string;
  posted_date: string;
  description: string;
  amount: string;
  direction: string;
  account_name: string;
  category_hint: string | null;
};

type MonthlySummary = {
  year: number;
  month: number;
  debits: number;
  credits: number;
  net_spend: number;
  transaction_count: number;
};

function App() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [summary, setSummary] = useState<MonthlySummary[]>([]);
  const [message, setMessage] = useState("What are my biggest transactions?");
  const [answer, setAnswer] = useState("");
  const [status, setStatus] = useState("");

  const refresh = async () => {
    const [transactionResponse, summaryResponse] = await Promise.all([
      fetch(`${API_BASE_URL}/transactions?limit=25`),
      fetch(`${API_BASE_URL}/analytics/monthly-summary`),
    ]);
    setTransactions(await transactionResponse.json());
    setSummary(await summaryResponse.json());
  };

  useEffect(() => {
    refresh().catch(() => setStatus("Backend is not reachable yet."));
  }, []);

  const uploadStatement = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_BASE_URL}/imports/chase-pdf`, {
      method: "POST",
      body: formData,
    });
    const result = await response.json();
    setStatus(`${result.status}: ${result.transactions_imported} transactions imported`);
    await refresh();
  };

  const askAgent = async () => {
    const response = await fetch(`${API_BASE_URL}/agent/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const result = await response.json();
    setAnswer(`${result.answer} Tool: ${result.selected_tool}`);
  };

  return (
    <main className="app">
      <header className="topbar">
        <div>
          <h1>Finance Guardian</h1>
          <p>Local-first transaction import, analytics, and grounded finance chat.</p>
        </div>
        <button className="iconButton" onClick={refresh} title="Refresh">
          <RefreshCw size={18} />
        </button>
      </header>

      <section className="grid">
        <div className="panel">
          <div className="panelHeader">
            <FileUp size={18} />
            <h2>Import</h2>
          </div>
          <input type="file" accept="application/pdf" onChange={uploadStatement} />
          <p className="status">{status || "Upload a Chase PDF statement to start."}</p>
        </div>

        <div className="panel">
          <div className="panelHeader">
            <Bot size={18} />
            <h2>Agent</h2>
          </div>
          <div className="agentRow">
            <input value={message} onChange={(event) => setMessage(event.target.value)} />
            <button className="iconButton" onClick={askAgent} title="Ask">
              <Search size={18} />
            </button>
          </div>
          <p className="answer">{answer || "The MVP agent routes questions to deterministic tools."}</p>
        </div>
      </section>

      <section className="section">
        <h2>Monthly Summary</h2>
        <div className="summaryGrid">
          {summary.map((row) => (
            <div className="metric" key={`${row.year}-${row.month}`}>
              <span>{row.year}-{String(row.month).padStart(2, "0")}</span>
              <strong>${Number(row.net_spend).toFixed(2)}</strong>
              <small>{row.transaction_count} transactions</small>
            </div>
          ))}
          {summary.length === 0 && <p>No monthly data yet.</p>}
        </div>
      </section>

      <section className="section">
        <h2>Transactions</h2>
        <div className="table">
          {transactions.map((transaction) => (
            <div className="tableRow" key={transaction.id}>
              <span>{transaction.posted_date}</span>
              <span>{transaction.description}</span>
              <span>{transaction.direction}</span>
              <strong>${transaction.amount}</strong>
            </div>
          ))}
          {transactions.length === 0 && <p>No transactions imported yet.</p>}
        </div>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
