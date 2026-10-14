import { useCallback, useEffect, useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import {
  ArrowDownLeft, ArrowRight, ArrowUpRight, Bot, Building2, ChartNoAxesCombined,
  Check, FileUp, LayoutDashboard, List, Menu, RefreshCw, Search, Settings2,
  Sparkles, Tags, Trash2, WalletCards, X,
} from "lucide-react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const pages = ["overview", "transactions", "reports", "accounts", "settings"] as const;
type Page = typeof pages[number];

type Transaction = {
  id: string;
  posted_date: string;
  description: string;
  amount: string;
  direction: "debit" | "credit";
  is_pending: boolean;
  account_name: string;
  canonical_merchant_name: string | null;
  category_name: string;
  subcategory_id: string | null;
  categorization_source: string | null;
};
type MonthlySummary = {
  year: number; month: number;
  posted_debits: number; posted_credits: number;
  pending_debits: number; pending_credits: number;
  posted_transaction_count: number; pending_transaction_count: number;
};
type Category = {
  category_id: string; display_name: string;
  subcategories: { category_id: string; display_name: string }[];
};
type CategorySpending = {
  parent_category_id: string; parent_category: string;
  posted_amount: number; pending_amount: number;
};
type CategoryTotal = {
  id: string; name: string; posted: number; pending: number;
};
type MonthlyLimit = { category_id: string; amount: string };
type CategorizationJob = {
  id: string; normalized_merchant: string; transaction_count: number; status: string;
};
type CategorizationSummary = {
  total_transactions: number; categorized_transactions: number;
  uncategorized_transactions: number; jobs: Record<string, number>;
};
type PlaidAccount = {
  account_id: string; name: string; mask: string | null;
  current_balance: string | null; available_balance: string | null;
  iso_currency_code: string | null;
};
type PlaidItem = {
  item_id: string; institution_name: string | null; status: string;
  accounts: PlaidAccount[];
};
type PlaidHandler = { open: () => void };

declare global {
  interface Window {
    Plaid?: {
      create: (options: {
        token: string;
        onSuccess: (publicToken: string, metadata: Record<string, unknown>) => void;
        onExit?: () => void;
      }) => PlaidHandler;
    };
  }
}

const money = (value: number) => new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 2,
}).format(value);
const shortMoney = (value: number) => new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 0,
}).format(value);
const currentMonth = () => {
  const today = new Date();
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
};
const monthLabel = (key: string) => new Intl.DateTimeFormat("en-US", {
  month: "long", year: "numeric", timeZone: "UTC",
}).format(new Date(`${key}-01T00:00:00Z`));
const monthRange = (key: string) => {
  const [year, month] = key.split("-").map(Number);
  const lastDay = new Date(year, month, 0).getDate();
  return { start: `${key}-01`, end: `${key}-${String(lastDay).padStart(2, "0")}` };
};
const readJson = async <T,>(response: Response): Promise<T> => {
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail ?? "Request failed. Please try again.");
  return body as T;
};
const isPage = (value: string): value is Page => pages.includes(value as Page);

function SummaryCard({ label, posted, pending, tone, note }: {
  label: string; posted: number; pending: number; tone: string; note?: string;
}) {
  const pendingSign = pending < 0 ? "−" : "+";
  return <article className={`summaryCard ${tone}`}>
    <div className="summaryCardTop"><span>{label}</span><span className="statusDot" /></div>
    <strong className="summaryValue">{money(posted)}</strong>
    <div className="pendingLine"><span>{pendingSign} {money(Math.abs(pending))} pending</span></div>
    <div className="summaryFoot"><span>Projected {money(posted + pending)}</span>{note && <span>{note}</span>}</div>
  </article>;
}

function TrendChart({ rows }: { rows: MonthlySummary[] }) {
  const recent = rows.slice(-6);
  if (recent.length === 0) return <EmptyState title="No trend yet" detail="Connect a bank or import a statement to see monthly cash flow." />;
  const max = Math.max(1, ...recent.flatMap((row) => [Number(row.posted_debits), Number(row.posted_credits)]));
  const x = (index: number) => 42 + index * (510 / Math.max(1, recent.length - 1));
  const y = (value: number) => 164 - (value / max) * 128;
  const points = (key: "posted_debits" | "posted_credits") => recent.map((row, index) => `${x(index)},${y(Number(row[key]))}`).join(" ");
  return <div className="trendChart">
    <div className="chartLegend"><span className="legendOut">Money out</span><span className="legendIn">Money in</span><span className="legendNote">Posted transactions</span></div>
    <svg viewBox="0 0 594 210" role="img" aria-label="Monthly posted money in and money out trend" preserveAspectRatio="none">
      {[0, 0.5, 1].map((tick) => <g key={tick}>
        <line x1="42" x2="552" y1={y(max * tick)} y2={y(max * tick)} className="chartGrid" />
        <text x="4" y={y(max * tick) + 4} className="axisLabel">{shortMoney(max * tick)}</text>
      </g>)}
      <polyline points={points("posted_debits")} className="chartLine chartLineOut" />
      <polyline points={points("posted_credits")} className="chartLine chartLineIn" />
      {recent.map((row, index) => <g key={`${row.year}-${row.month}`}>
        <circle cx={x(index)} cy={y(Number(row.posted_debits))} r="4" className="chartPointOut" />
        <circle cx={x(index)} cy={y(Number(row.posted_credits))} r="4" className="chartPointIn" />
        <text x={x(index)} y="198" textAnchor="middle" className="axisLabel">
          {new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" }).format(new Date(Date.UTC(row.year, row.month - 1, 1)))}
        </text>
      </g>)}
    </svg>
  </div>;
}

function CategoryBars({ rows, limits, showLimits = true }: {
  rows: CategoryTotal[]; limits: MonthlyLimit[]; showLimits?: boolean;
}) {
  const limitMap = new Map(limits.map((limit) => [limit.category_id, Number(limit.amount)]));
  if (rows.length === 0) return <EmptyState title="No spending for this month" detail="Category spending will appear after transactions are synced or imported." />;
  const scale = Math.max(1, ...rows.flatMap((row) => [
    row.posted + row.pending,
    showLimits ? (limitMap.get(row.id) ?? 0) : 0,
  ]));
  return <div className="categoryBars">
    {rows.map((row) => {
      const limit = showLimits ? limitMap.get(row.id) : undefined;
      const projected = row.posted + row.pending;
      const postedWidth = Math.max(0, Math.min(100, (row.posted / scale) * 100));
      const pendingWidth = Math.max(0, Math.min(100 - postedWidth, (row.pending / scale) * 100));
      const remaining = limit === undefined ? null : limit - projected;
      return <div className="categoryBar" key={row.id}>
        <div className="categoryBarTop"><strong>{row.name}</strong><span>{money(projected)}</span></div>
        <div className="categoryTrack" role="img" aria-label={`${row.name}: ${money(row.posted)} posted, ${money(row.pending)} pending${limit === undefined ? "" : `, ${money(limit)} monthly limit`}`}>
          <div className="categoryPosted" style={{ width: `${postedWidth}%` }} />
          <div className="categoryPending" style={{ width: `${pendingWidth}%` }} />
          {limit !== undefined && <span className="limitMarker" style={{ left: `${Math.min(99, (limit / scale) * 100)}%` }} />}
        </div>
        <div className="categoryBarFoot">
          <span>{money(row.posted)} posted{row.pending > 0 ? ` · ${money(row.pending)} pending` : ""}</span>
          <span className={remaining !== null && remaining < 0 ? "overLimit" : ""}>
            {remaining === null ? (showLimits ? "No limit set" : "") : remaining < 0 ? `${money(-remaining)} over limit` : `${money(remaining)} left of ${money(limit!)}`}
          </span>
        </div>
      </div>;
    })}
    {showLimits && <div className="barKey"><span className="keyPosted">Posted</span><span className="keyPending">Pending</span><span className="keyLimit">Monthly limit</span></div>}
  </div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="emptyState"><WalletCards size={24} /><strong>{title}</strong><p>{detail}</p></div>;
}

export default function App() {
  const [page, setPage] = useState<Page>(() => {
    const hash = window.location.hash.slice(1);
    return isPage(hash) ? hash : "overview";
  });
  const [mobileMenu, setMobileMenu] = useState(false);
  const [month, setMonth] = useState(currentMonth);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [recentTransactions, setRecentTransactions] = useState<Transaction[]>([]);
  const [summary, setSummary] = useState<MonthlySummary[]>([]);
  const [spending, setSpending] = useState<CategorySpending[]>([]);
  const [limits, setLimits] = useState<MonthlyLimit[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [plaidItems, setPlaidItems] = useState<PlaidItem[]>([]);
  const [jobs, setJobs] = useState<CategorizationJob[]>([]);
  const [categorizationSummary, setCategorizationSummary] = useState<CategorizationSummary | null>(null);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [limitCategory, setLimitCategory] = useState("");
  const [limitAmount, setLimitAmount] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");

  useEffect(() => {
    const onHashChange = () => {
      const hash = window.location.hash.slice(1);
      if (isPage(hash)) setPage(hash);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = (next: Page) => {
    window.location.hash = next;
    setPage(next);
    setMobileMenu(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const refresh = useCallback(async () => {
    const { start, end } = monthRange(month);
    const query = new URLSearchParams({ limit: "100" });
    if (searchQuery) query.set("query", searchQuery);
    const urls = [
      `/transactions?${query}`, "/analytics/monthly-summary",
      `/analytics/category-spending?start_date=${start}&end_date=${end}`,
      "/budgets/monthly-limits", "/categorization/categories", "/plaid/items",
      "/categorization/jobs?limit=100", "/categorization/summary", "/transactions?limit=5",
    ];
    try {
      const responses = await Promise.all(urls.map((url) => fetch(`${API_BASE_URL}${url}`)));
      const [nextTransactions, nextSummary, nextSpending, nextLimits, nextCategories, nextItems, nextJobs, nextCategorizationSummary, nextRecent] = await Promise.all([
        readJson<Transaction[]>(responses[0]), readJson<MonthlySummary[]>(responses[1]),
        readJson<CategorySpending[]>(responses[2]), readJson<MonthlyLimit[]>(responses[3]),
        readJson<Category[]>(responses[4]), readJson<PlaidItem[]>(responses[5]),
        readJson<CategorizationJob[]>(responses[6]), readJson<CategorizationSummary>(responses[7]),
        readJson<Transaction[]>(responses[8]),
      ]);
      setTransactions(nextTransactions);
      setRecentTransactions(nextRecent);
      setSummary(nextSummary);
      setSpending(nextSpending);
      setLimits(nextLimits);
      setCategories(nextCategories);
      setPlaidItems(nextItems);
      setJobs(nextJobs);
      setCategorizationSummary(nextCategorizationSummary);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Unable to load your data.");
    } finally {
      setLoading(false);
    }
  }, [month, searchQuery]);

  useEffect(() => { void refresh(); }, [refresh]);

  const selectedSummary = summary.find((row) => `${row.year}-${String(row.month).padStart(2, "0")}` === month);
  const postedOut = Number(selectedSummary?.posted_debits ?? 0);
  const pendingOut = Number(selectedSummary?.pending_debits ?? 0);
  const postedIn = Number(selectedSummary?.posted_credits ?? 0);
  const pendingIn = Number(selectedSummary?.pending_credits ?? 0);
  const categoryTotals = useMemo(() => {
    const grouped = new Map<string, CategoryTotal>();
    for (const row of spending) {
      const existing = grouped.get(row.parent_category_id) ?? {
        id: row.parent_category_id, name: row.parent_category, posted: 0, pending: 0,
      };
      existing.posted += Number(row.posted_amount);
      existing.pending += Number(row.pending_amount);
      grouped.set(row.parent_category_id, existing);
    }
    return [...grouped.values()].sort((a, b) => (b.posted + b.pending) - (a.posted + a.pending));
  }, [spending]);
  const topCategories = categoryTotals.slice(0, 5);
  const expenseCategories = categories.filter((category) => category.category_id !== "income" && category.category_id !== "other");

  const runAction = async (action: () => Promise<void>) => {
    setBusy(true);
    try { await action(); } catch (error) {
      setNotice(error instanceof Error ? error.message : "Something went wrong.");
    } finally { setBusy(false); }
  };

  const saveLimit = (event: FormEvent) => {
    event.preventDefault();
    if (!limitCategory || !limitAmount) return;
    void runAction(async () => {
      await readJson(await fetch(`${API_BASE_URL}/budgets/monthly-limits/${limitCategory}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount: limitAmount }),
      }));
      setNotice("Monthly limit saved.");
      setLimitAmount("");
      await refresh();
    });
  };

  const removeLimit = (categoryId: string) => void runAction(async () => {
    const response = await fetch(`${API_BASE_URL}/budgets/monthly-limits/${categoryId}`, { method: "DELETE" });
    if (!response.ok) throw new Error("Could not remove the limit.");
    setNotice("Monthly limit removed.");
    await refresh();
  });

  const updateCategory = (transactionId: string, categoryId: string) => void runAction(async () => {
    await readJson(await fetch(`${API_BASE_URL}/categorization/transactions/${transactionId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category_id: categoryId, apply_to_matching_merchant: true }),
    }));
    setNotice("Category updated for matching merchant transactions.");
    await refresh();
  });

  const loadPlaidScript = async () => {
    if (window.Plaid) return;
    await new Promise<void>((resolve, reject) => {
      const existing = document.querySelector<HTMLScriptElement>("script[data-plaid-link]");
      if (existing) {
        existing.addEventListener("load", () => resolve(), { once: true });
        existing.addEventListener("error", () => reject(new Error("Plaid Link failed to load.")), { once: true });
        return;
      }
      const script = document.createElement("script");
      script.src = "https://cdn.plaid.com/link/v2/stable/link-initialize.js";
      script.async = true;
      script.dataset.plaidLink = "true";
      script.onload = () => resolve();
      script.onerror = () => reject(new Error("Plaid Link failed to load."));
      document.head.appendChild(script);
    });
  };

  const syncBanks = () => void runAction(async () => {
    const result = await readJson<{ items_synced: number; transactions_added: number }>(await fetch(`${API_BASE_URL}/plaid/sync-transactions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
    setNotice(`${result.items_synced} connection synced · ${result.transactions_added} transactions added.`);
    await refresh();
  });

  const connectBank = () => void runAction(async () => {
    await loadPlaidScript();
    const token = await readJson<{ link_token: string }>(await fetch(`${API_BASE_URL}/plaid/link-token`, { method: "POST" }));
    if (!window.Plaid) throw new Error("Plaid Link could not be started.");
    window.Plaid.create({
      token: token.link_token,
      onSuccess: (publicToken, metadata) => {
        void runAction(async () => {
          await readJson(await fetch(`${API_BASE_URL}/plaid/exchange-public-token`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ public_token: publicToken, metadata }),
          }));
          await readJson(await fetch(`${API_BASE_URL}/plaid/sync-transactions`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
          }));
          setNotice("Bank connected and transactions synced.");
          await refresh();
        });
      },
      onExit: () => setNotice("Bank connection closed."),
    }).open();
  });

  const uploadStatement = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    void runAction(async () => {
      const data = new FormData();
      data.append("file", file);
      const result = await readJson<{ transactions_imported: number }>(await fetch(`${API_BASE_URL}/imports/chase-pdf`, {
        method: "POST", body: data,
      }));
      setNotice(`${result.transactions_imported} transactions imported from statement.`);
      event.target.value = "";
      await refresh();
    });
  };

  const runCategorization = (path: string) => void runAction(async () => {
    await readJson(await fetch(`${API_BASE_URL}/categorization/${path}`, { method: "POST" }));
    setNotice("Categorization updated.");
    await refresh();
  });

  const askGuardian = (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim()) return;
    void runAction(async () => {
      const result = await readJson<{ answer: string }>(await fetch(`${API_BASE_URL}/agent/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question.trim() }),
      }));
      setAnswer(result.answer);
    });
  };

  const monthSelect = <label className="monthPicker">
    <span>Period</span>
    <input type="month" value={month} max={currentMonth()} onChange={(event) => { if (event.target.value) setMonth(event.target.value); }} aria-label="Select month" />
  </label>;

  return <div className="appShell">
    <aside className={`sidebar ${mobileMenu ? "sidebarOpen" : ""}`}>
      <div className="brand"><div className="brandMark"><WalletCards size={20} /></div><div><strong>Finance Guardian</strong><span>Personal finance</span></div></div>
      <div className="navLabel">WORKSPACE</div>
      <nav aria-label="Main navigation">
        <button className={page === "overview" ? "navItem active" : "navItem"} onClick={() => navigate("overview")} aria-current={page === "overview" ? "page" : undefined}><LayoutDashboard size={18} />Overview</button>
        <button className={page === "transactions" ? "navItem active" : "navItem"} onClick={() => navigate("transactions")} aria-current={page === "transactions" ? "page" : undefined}><List size={18} />Transactions</button>
        <button className={page === "reports" ? "navItem active" : "navItem"} onClick={() => navigate("reports")} aria-current={page === "reports" ? "page" : undefined}><ChartNoAxesCombined size={18} />Reports</button>
      </nav>
      <div className="navLabel utilityLabel">MANAGE</div>
      <nav aria-label="Management navigation">
        <button className={page === "accounts" ? "navItem active" : "navItem"} onClick={() => navigate("accounts")} aria-current={page === "accounts" ? "page" : undefined}><Building2 size={18} />Accounts</button>
        <button className={page === "settings" ? "navItem active" : "navItem"} onClick={() => navigate("settings")} aria-current={page === "settings" ? "page" : undefined}><Settings2 size={18} />Settings</button>
      </nav>
      <div className="sidebarFoot"><span className="liveDot" />Local workspace</div>
    </aside>
    {mobileMenu && <button className="mobileBackdrop" aria-label="Close menu" onClick={() => setMobileMenu(false)} />}

    <main className="mainContent">
      <header className="topbar">
        <div className="topbarLead"><button className="mobileMenuButton iconButton" onClick={() => setMobileMenu(!mobileMenu)} aria-label={mobileMenu ? "Close menu" : "Open menu"}>{mobileMenu ? <X size={20} /> : <Menu size={20} />}</button><div className="eyebrow">YOUR MONEY, IN FOCUS</div></div>
        <div className="topbarActions"><span className="topbarDate">{monthLabel(currentMonth())}</span><button className="iconButton" onClick={() => void refresh()} title="Refresh data" aria-label="Refresh data" disabled={busy}><RefreshCw size={18} /></button></div>
      </header>
      {notice && <div className="notice" role="status"><span>{notice}</span><button onClick={() => setNotice("")} aria-label="Dismiss message"><X size={16} /></button></div>}
      {loading && <p className="loadingText">Loading your financial picture…</p>}

      {page === "overview" && <>
        <div className="pageHeading"><div><div className="eyebrow">OVERVIEW</div><h1>Financial overview</h1><p>A clear view of what came in, what went out, and what is still pending.</p></div>{monthSelect}</div>
        {summary.length === 0 && <div className="welcomeBanner"><div><strong>Start with your transactions</strong><p>Connect a bank or upload a statement to see your cash flow and spending patterns.</p></div><button className="primaryButton" onClick={() => navigate("accounts")}>Go to accounts <ArrowRight size={16} /></button></div>}
        <section className="summaryGrid" aria-label="Cash flow summary">
          <SummaryCard label="Money out" posted={postedOut} pending={pendingOut} tone="out" note="This month" />
          <SummaryCard label="Money in" posted={postedIn} pending={pendingIn} tone="in" note="Includes all credits" />
          <SummaryCard label="Net cash flow" posted={postedIn - postedOut} pending={pendingIn - pendingOut} tone="net" note="In minus out" />
        </section>
        <div className="dashboardGrid">
          <section className="surface trendPanel"><div className="sectionTitle"><div><span className="eyebrow">THE BIG PICTURE</span><h2>Cash flow trend</h2></div><span className="sectionHint">Last 6 months</span></div><TrendChart rows={summary} /></section>
          <section className="surface categoryPanel"><div className="sectionTitle"><div><span className="eyebrow">WHERE IT WENT</span><h2>Top 5 categories</h2></div><button className="textButton" onClick={() => navigate("reports")}>All categories <ArrowRight size={15} /></button></div><p className="sectionDescription">Projected spending includes posted and pending transactions.</p><CategoryBars rows={topCategories} limits={limits} showLimits={month === currentMonth()} /><button className="textButton manageLink" onClick={() => navigate("settings")}>Manage monthly limits <ArrowRight size={15} /></button></section>
        </div>
        <section className="surface recentPanel"><div className="sectionTitle"><div><span className="eyebrow">LATEST ACTIVITY</span><h2>Recent transactions</h2></div><button className="textButton" onClick={() => navigate("transactions")}>View all <ArrowRight size={15} /></button></div><TransactionList rows={recentTransactions} compact /></section>
      </>}

      {page === "transactions" && <>
        <div className="pageHeading"><div><div className="eyebrow">ACTIVITY</div><h1>Transactions</h1><p>Find activity and keep categories accurate.</p></div><span className="pageCount">Latest 100 results</span></div>
        <section className="surface"><form className="searchBar" onSubmit={(event) => { event.preventDefault(); setSearchQuery(searchInput.trim()); }}><Search size={18} /><input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search merchant or description" aria-label="Search transactions" /><button className="primaryButton" type="submit">Search</button>{searchQuery && <button className="textButton" type="button" onClick={() => { setSearchInput(""); setSearchQuery(""); }}>Clear</button>}</form><div className="tableWrap"><table className="transactionTable"><thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Account</th><th className="amountCell">Amount</th></tr></thead><tbody>{transactions.map((transaction) => <tr key={transaction.id}><td>{transaction.posted_date}</td><td><strong>{transaction.canonical_merchant_name ?? transaction.description}</strong><small>{transaction.is_pending ? "Pending" : "Posted"}</small></td><td><select aria-label={`Category for ${transaction.description}`} value={transaction.subcategory_id ?? ""} onChange={(event) => updateCategory(transaction.id, event.target.value)} disabled={busy}><option value="">Uncategorized</option>{categories.map((category) => <optgroup key={category.category_id} label={category.display_name}>{category.subcategories.map((sub) => <option key={sub.category_id} value={sub.category_id}>{sub.display_name}</option>)}</optgroup>)}</select></td><td>{transaction.account_name}</td><td className={`amountCell ${transaction.direction === "credit" ? "positive" : ""}`}>{transaction.direction === "credit" ? "+" : "−"}{money(Number(transaction.amount))}</td></tr>)}</tbody></table>{transactions.length === 0 && <EmptyState title={searchQuery ? "No matching transactions" : "No transactions yet"} detail={searchQuery ? "Try a different search." : "Connect a bank or import a statement to get started."} />}</div></section>
      </>}

      {page === "reports" && <>
        <div className="pageHeading"><div><div className="eyebrow">PATTERNS</div><h1>Reports</h1><p>Compare cash flow over time and explore where spending happened.</p></div>{monthSelect}</div>
        <div className="reportSummary"><div className="reportMetric"><span>Posted money out</span><strong>{money(postedOut)}</strong></div><div className="reportMetric"><span>Posted money in</span><strong>{money(postedIn)}</strong></div><div className="reportMetric"><span>Posted net flow</span><strong>{money(postedIn - postedOut)}</strong></div></div>
        <section className="surface reportTrend"><div className="sectionTitle"><div><span className="eyebrow">MONTH BY MONTH</span><h2>Cash flow trend</h2></div></div><TrendChart rows={summary} /></section>
        <section className="surface"><div className="sectionTitle"><div><span className="eyebrow">SPENDING DETAIL</span><h2>{monthLabel(month)} by category</h2></div></div><p className="sectionDescription">Posted spending with pending activity shown separately. Monthly limits appear on the current month.</p><CategoryBars rows={categoryTotals} limits={limits} showLimits={month === currentMonth()} /></section>
      </>}

      {page === "accounts" && <>
        <div className="pageHeading"><div><div className="eyebrow">DATA SOURCES</div><h1>Accounts & connections</h1><p>Manage connected institutions and keep transaction data fresh.</p></div></div>
        <div className="accountActions"><button className="primaryButton" onClick={connectBank} disabled={busy}><Building2 size={17} />Connect bank</button><button className="secondaryButton" onClick={syncBanks} disabled={busy || plaidItems.length === 0}><RefreshCw size={17} />Sync transactions</button></div>
        <section className="surface"><div className="sectionTitle"><div><span className="eyebrow">CONNECTED</span><h2>Institutions</h2></div><span className="sectionHint">{plaidItems.length} connected</span></div>{plaidItems.length === 0 ? <EmptyState title="No bank connections" detail="Connect a bank to bring your accounts and transactions together." /> : <div className="institutionList">{plaidItems.map((item) => <div className="institution" key={item.item_id}><div className="institutionHead"><div className="institutionIcon"><Building2 size={21} /></div><div><strong>{item.institution_name ?? "Connected institution"}</strong><span>{item.accounts.length} accounts</span></div><span className="connectionStatus"><Check size={14} />{item.status}</span></div>{item.accounts.map((account) => <div className="accountRow" key={account.account_id}><span>{account.name}{account.mask ? ` ····${account.mask}` : ""}</span><strong>{account.current_balance === null ? "Balance unavailable" : money(Number(account.current_balance))}</strong></div>)}</div>)}</div>}</section>
        <section className="surface importPanel"><div><div className="eyebrow">SUPPLEMENTAL HISTORY</div><h2>Import a statement</h2><p>Upload a Chase PDF statement to add transactions that are not yet available through your bank connection.</p></div><label className="secondaryButton uploadButton"><FileUp size={17} />Choose PDF<input type="file" accept="application/pdf" onChange={uploadStatement} disabled={busy} /></label></section>
      </>}

      {page === "settings" && <>
        <div className="pageHeading"><div><div className="eyebrow">PREFERENCES</div><h1>Settings</h1><p>Set spending limits and keep your transaction categories organized.</p></div></div>
        <section className="surface"><div className="sectionTitle"><div><span className="eyebrow">MONTHLY PLANNING</span><h2>Category limits</h2></div></div><p className="sectionDescription">Limits repeat each month and apply to parent spending categories. The current month chart compares them with posted and pending spending.</p><form className="limitForm" onSubmit={saveLimit}><label>Category<select value={limitCategory} onChange={(event) => { const id = event.target.value; setLimitCategory(id); setLimitAmount(limits.find((limit) => limit.category_id === id)?.amount ?? ""); }} required><option value="">Choose a category</option>{expenseCategories.map((category) => <option key={category.category_id} value={category.category_id}>{category.display_name}</option>)}</select></label><label>Monthly limit<input type="number" min="0.01" step="0.01" placeholder="0.00" value={limitAmount} onChange={(event) => setLimitAmount(event.target.value)} required /></label><button className="primaryButton" type="submit" disabled={busy}>Save limit</button></form>{limits.length > 0 && <div className="limitList">{limits.map((limit) => <div className="limitRow" key={limit.category_id}><span>{categories.find((category) => category.category_id === limit.category_id)?.display_name ?? limit.category_id}</span><strong>{money(Number(limit.amount))} / month</strong><button className="iconButton subtleButton" onClick={() => removeLimit(limit.category_id)} aria-label={`Remove limit for ${limit.category_id}`} disabled={busy}><Trash2 size={16} /></button></div>)}</div>}</section>
        <section className="surface"><div className="sectionTitle"><div><span className="eyebrow">DATA QUALITY</span><h2>Categorization</h2></div></div><p className="sectionDescription">{categorizationSummary ? `${categorizationSummary.categorized_transactions} of ${categorizationSummary.total_transactions} transactions categorized · ${categorizationSummary.uncategorized_transactions} uncategorized` : "Categorization status unavailable."}</p><div className="inlineActions"><button className="secondaryButton" onClick={() => runCategorization("apply-known")} disabled={busy}><Tags size={16} />Apply known aliases</button><button className="secondaryButton" onClick={() => runCategorization("categorize-unknowns")} disabled={busy}><Sparkles size={16} />Categorize unknowns</button></div>{jobs.some((job) => job.status === "pending") && <div className="jobList"><strong>Pending merchants</strong>{jobs.filter((job) => job.status === "pending").slice(0, 8).map((job) => <div key={job.id}><span>{job.normalized_merchant}</span><small>{job.transaction_count} transactions</small></div>)}</div>}</section>
        <section className="surface guardianPanel"><div className="sectionTitle"><div><span className="eyebrow">EXPERIMENTAL</span><h2>Ask Guardian</h2></div><Bot size={20} /></div><p className="sectionDescription">Ask a question about your imported transactions. Requires a configured LLM provider.</p><form className="searchBar" onSubmit={askGuardian}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What were my biggest transactions?" aria-label="Question for Guardian" /><button className="primaryButton" type="submit" disabled={busy}>Ask</button></form>{answer && <p className="guardianAnswer">{answer}</p>}</section>
      </>}
    </main>
  </div>;
}

function TransactionList({ rows }: { rows: Transaction[]; compact?: boolean }) {
  if (rows.length === 0) return <EmptyState title="No recent activity" detail="Your latest transactions will appear here." />;
  return <div className="recentList">{rows.map((row) => <div className="recentRow" key={row.id}><div className={`transactionGlyph ${row.direction === "credit" ? "creditGlyph" : ""}`}>{row.direction === "credit" ? <ArrowDownLeft size={18} /> : <ArrowUpRight size={18} />}</div><div className="recentName"><strong>{row.canonical_merchant_name ?? row.description}</strong><span>{row.category_name} · {row.posted_date}{row.is_pending ? " · Pending" : ""}</span></div><strong className={row.direction === "credit" ? "positive" : ""}>{row.direction === "credit" ? "+" : "−"}{money(Number(row.amount))}</strong></div>)}</div>;
}
