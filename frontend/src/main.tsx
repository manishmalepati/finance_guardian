import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Bot, FileUp, RefreshCw, Search, Sparkles, Tags } from "lucide-react";
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
  category_id: string | null;
  category_name: string;
  canonical_merchant_name: string | null;
  categorization_source: string | null;
  categorization_confidence: string | null;
};

type MonthlySummary = {
  year: number;
  month: number;
  debits: number;
  credits: number;
  net_spend: number;
  transaction_count: number;
};

type Category = {
  category_id: string;
  display_name: string;
};

type CategorizationJob = {
  id: string;
  normalized_merchant: string;
  example_descriptions: string[];
  transaction_count: number;
  status: string;
  error_message: string | null;
};

type CategorizationSummary = {
  total_transactions: number;
  categorized_transactions: number;
  uncategorized_transactions: number;
  jobs: Record<string, number>;
};

function App() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [jobs, setJobs] = useState<CategorizationJob[]>([]);
  const [categorizationSummary, setCategorizationSummary] = useState<CategorizationSummary | null>(null);
  const [summary, setSummary] = useState<MonthlySummary[]>([]);
  const [message, setMessage] = useState("What are my biggest transactions?");
  const [answer, setAnswer] = useState("");
  const [status, setStatus] = useState("");

  const refresh = async () => {
    const [transactionResponse, categoryResponse, jobsResponse, categorizationSummaryResponse, summaryResponse] =
      await Promise.all([
      fetch(`${API_BASE_URL}/transactions?limit=100`),
      fetch(`${API_BASE_URL}/categorization/categories`),
      fetch(`${API_BASE_URL}/categorization/jobs?limit=100`),
      fetch(`${API_BASE_URL}/categorization/summary`),
      fetch(`${API_BASE_URL}/analytics/monthly-summary`),
    ]);
    setTransactions(await transactionResponse.json());
    setCategories(await categoryResponse.json());
    setJobs(await jobsResponse.json());
    setCategorizationSummary(await categorizationSummaryResponse.json());
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
    setStatus(
      `${result.status}: ${result.transactions_imported} imported, ${result.transactions_categorized ?? 0} categorized`
    );
    await refresh();
  };

  const askAgent = async () => {
    const response = await fetch(`${API_BASE_URL}/agent/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const result = await response.json();
    if (!response.ok) {
      setAnswer(result.detail ?? "Agent is not configured yet.");
      return;
    }
    setAnswer(`${result.answer} Tool: ${result.selected_tool}`);
  };

  const applyKnownAliases = async () => {
    const response = await fetch(`${API_BASE_URL}/categorization/apply-known`, { method: "POST" });
    const result = await response.json();
    setStatus(
      `${result.transactions_categorized} transactions categorized, ${result.unknown_merchants_queued} merchants queued`
    );
    await refresh();
  };

  const categorizeUnknowns = async () => {
    const response = await fetch(`${API_BASE_URL}/categorization/categorize-unknowns`, { method: "POST" });
    const result = await response.json();
    if (!response.ok) {
      setStatus(result.detail ?? "LLM categorization failed.");
      return;
    }
    setStatus(`${result.jobs_processed} merchant jobs processed, ${result.transactions_categorized} transactions categorized`);
    await refresh();
  };

  const updateTransactionCategory = async (transactionId: string, categoryId: string) => {
    if (!categoryId) return;
    const response = await fetch(`${API_BASE_URL}/categorization/transactions/${transactionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category_id: categoryId, apply_to_matching_merchant: true }),
    });
    const result = await response.json();
    if (!response.ok) {
      setStatus(result.detail ?? "Category update failed.");
      return;
    }
    setStatus(`${result.matching_transactions_updated} matching transactions updated`);
    await refresh();
  };

  const pendingJobs = jobs.filter((job) => job.status === "pending");
  const recentlyResolvedJobs = jobs.filter((job) => job.status !== "pending").slice(0, 8);

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
          <p className="answer">{answer || "Chat requires a configured LLM provider and API key."}</p>
        </div>
      </section>

      <section className="section">
        <div className="sectionHeader">
          <div>
            <h2>Categorization</h2>
            <small>
              {categorizationSummary
                ? `${categorizationSummary.categorized_transactions}/${categorizationSummary.total_transactions} categorized, ${categorizationSummary.uncategorized_transactions} uncategorized, ${categorizationSummary.jobs.pending ?? 0} pending jobs`
                : "Loading categorization status"}
            </small>
          </div>
          <div className="actions">
            <button className="actionButton" onClick={applyKnownAliases}>
              <Tags size={16} />
              Apply aliases
            </button>
            <button className="actionButton" onClick={categorizeUnknowns}>
              <Sparkles size={16} />
              Categorize unknowns
            </button>
          </div>
        </div>
        <div className="jobSubhead">
          <strong>Pending Merchants</strong>
          <small>{pendingJobs.length} shown</small>
        </div>
        <div className="jobGrid">
          {pendingJobs.map((job) => (
            <div className="job" key={job.id}>
              <strong>{job.normalized_merchant}</strong>
              <span>{job.status}</span>
              <small>{job.transaction_count} transactions</small>
            </div>
          ))}
          {pendingJobs.length === 0 && <p>No pending merchant jobs.</p>}
        </div>
        {recentlyResolvedJobs.length > 0 && (
          <>
            <div className="jobSubhead">
              <strong>Recently Resolved</strong>
              <small>{recentlyResolvedJobs.length} shown</small>
            </div>
            <div className="jobGrid">
              {recentlyResolvedJobs.map((job) => (
                <div className="job" key={job.id}>
                  <strong>{job.normalized_merchant}</strong>
                  <span>{job.status}</span>
                  <small>{job.transaction_count} transactions</small>
                </div>
              ))}
            </div>
          </>
        )}
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
        <div className="sectionHeader">
          <h2>Transactions</h2>
          <small>{transactions.length} shown</small>
        </div>
        <div className="table">
          <div className="tableRow tableHead">
            <span>Date</span>
            <span>Merchant</span>
            <span>Description</span>
            <span>Category</span>
            <span>Source</span>
            <span>Amount</span>
          </div>
          {transactions.map((transaction) => (
            <div className="tableRow" key={transaction.id}>
              <span>{transaction.posted_date}</span>
              <span>{transaction.canonical_merchant_name ?? "Unknown"}</span>
              <span>{transaction.description}</span>
              <select
                value={transaction.category_id ?? ""}
                onChange={(event) => updateTransactionCategory(transaction.id, event.target.value)}
              >
                <option value="">Uncategorized</option>
                {categories.map((category) => (
                  <option key={category.category_id} value={category.category_id}>
                    {category.display_name}
                  </option>
                ))}
              </select>
              <span>{transaction.categorization_source ?? "none"}</span>
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
