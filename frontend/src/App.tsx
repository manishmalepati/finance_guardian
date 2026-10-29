import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import {
  ArrowDownLeft, ArrowRight, ArrowUpRight, Bot, Building2, ChartNoAxesCombined,
  Check, FileUp, LayoutDashboard, List, Menu, RefreshCw, Search, Settings2,
  Sparkles, Tags, Trash2, WalletCards, X,
} from "lucide-react";
import { CategoryShare, CategoryTrend } from "./ReportCharts";
import type { ReportMonth, SpendingReport } from "./ReportCharts";
import { CategoryFillTile } from "./CategoryFillTile";
import { GoalsPage } from "./GoalsPage";
import { ExplainSpendingPage } from "./ExplainSpendingPage";
import { RecurringChargesPanel } from "./RecurringChargesPanel";
import { AnomalyPanel } from "./AnomalyPanel";
import { BehavioralAlertsPanel } from "./BehavioralAlertsPanel";
import { ForecastPanel } from "./ForecastPanel";
import type { GoalEvaluation } from "./goalTypes";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const pages = ["overview", "transactions", "reports", "intelligence", "goals", "accounts", "settings"] as const;
type Page = typeof pages[number];

type Transaction = {
  id: string;
  posted_date: string;
  description: string;
  amount: string;
  direction: "debit" | "credit";
  is_pending: boolean;
  account_name: string;
  account_id: string | null;
  parent_category_id: string | null;
  canonical_merchant_name: string | null;
  category_name: string;
  subcategory_id: string | null;
  categorization_source: string | null;
  receipt_status: "matched" | "possible" | "no_receipt";
};
type OrderItem = {
  id: string; description: string; quantity: string | null;
  unit_price: string | null; line_total: string | null;
  category_id: string | null; evidence: string | null;
};
type ReceiptMatch = {
  match_id: string; status: "confirmed" | "suggested";
  confidence: string; reasons: string[];
  order: {
    id: string; merchant: string; merchant_order_id: string | null;
    placed_date: string | null; currency: string | null;
    subtotal: string | null; delivery_fee: string | null;
    tax: string | null; tip: string | null; other_fees: string | null;
    discount: string | null; total: string | null;
    parse_quality: string; items: OrderItem[];
    source: { message_id: string; sender: string | null; subject: string | null;
      received_at: string | null; parser_version: string } | null;
  };
};
type TransactionContext = {
  transaction: { id: string; merchant: string; amount: string; currency: string | null;
    direction: string; posted_date: string; authorized_date: string | null;
    is_pending: boolean; account_name: string };
  receipt_status: Transaction["receipt_status"];
  matches: ReceiptMatch[];
};
type GmailConnection = {
  id: string; email_address: string; status: string; last_sync_at: string | null;
  source_count: number; last_run: { status: string; imported: number;
    skipped: number; failed: number; completed_at: string | null } | null;
};
type OrderSearchResult = {
  id: string; merchant: string; placed_date: string | null;
  total: string | null; currency: string | null;
};
type Category = {
  category_id: string; display_name: string;
  subcategories: { category_id: string; display_name: string }[];
};
type CategoryTotal = {
  id: string; name: string; posted: number; pending: number;
};
type MonthlyLimit = { category_id: string; amount: string };
type CanonicalAccount = {
  id: string; name: string; mask: string | null; source: string;
  account_type: string | null; institution_name: string | null;
};
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
  item_id: string; institution_name: string | null; status: string; has_cursor: boolean;
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
const budgetMoney = (value: number) => new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 0, maximumFractionDigits: 2,
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
const previousMonth = (key: string) => {
  const [year, month] = key.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 2, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
};
const todayKey = () => {
  const today = new Date();
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
};
const reportStartKey = () => {
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth() - 5, 1);
  return `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-01`;
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

function TrendChart({ rows }: { rows: ReportMonth[] }) {
  const recent = rows;
  if (recent.every((row) => !row.posted_spending && !row.posted_money_in)) return <EmptyState title="No trend yet" detail="No posted spending or money in for this date range." />;
  const max = Math.max(1, ...recent.flatMap((row) => [Number(row.posted_spending), Number(row.posted_money_in)]));
  const x = (index: number) => 42 + index * (510 / Math.max(1, recent.length - 1));
  const y = (value: number) => 164 - (value / max) * 128;
  const points = (key: "posted_spending" | "posted_money_in") => recent.map((row, index) => `${x(index)},${y(Number(row[key]))}`).join(" ");
  return <div className="trendChart">
    <div className="chartLegend"><span className="legendOut">Spending</span><span className="legendIn">Money in</span><span className="legendNote">Posted · movements excluded</span></div>
    <svg viewBox="0 0 594 210" role="img" aria-label="Monthly posted money in and spending trend" preserveAspectRatio="none">
      {[0, 0.5, 1].map((tick) => <g key={tick}>
        <line x1="42" x2="552" y1={y(max * tick)} y2={y(max * tick)} className="chartGrid" />
        <text x="4" y={y(max * tick) + 4} className="axisLabel">{shortMoney(max * tick)}</text>
      </g>)}
      <polyline points={points("posted_spending")} className="chartLine chartLineOut" />
      <polyline points={points("posted_money_in")} className="chartLine chartLineIn" />
      {recent.map((row, index) => <g key={row.month}>
        <circle cx={x(index)} cy={y(Number(row.posted_spending))} r="4" className="chartPointOut" />
        <circle cx={x(index)} cy={y(Number(row.posted_money_in))} r="4" className="chartPointIn" />
        {(recent.length <= 8 || index % Math.ceil(recent.length / 8) === 0) && <text x={x(index)} y="198" textAnchor="middle" className="axisLabel">
          {new Intl.DateTimeFormat("en-US", { month: "short", year: "2-digit", timeZone: "UTC" }).format(new Date(`${row.month}T00:00:00Z`))}
        </text>}
      </g>)}
    </svg>
  </div>;
}

function CategoryBars({ rows, limits, showLimits = true, accountScoped = false, onSelect }: {
  rows: CategoryTotal[]; limits: MonthlyLimit[]; showLimits?: boolean;
  accountScoped?: boolean; onSelect?: (categoryId: string) => void;
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
      const hasLimit = limit !== undefined && limit > 0;
      const progress = hasLimit ? Math.max(0, projected / limit) : 0;
      const overage = hasLimit ? Math.max(0, projected - limit) : 0;
      const overflowWidth = overage > 0 && projected > 0 ? (overage / projected) * 100 : 0;
      const postedWidth = Math.max(0, Math.min(100, (row.posted / scale) * 100));
      const pendingWidth = Math.max(0, Math.min(100 - postedWidth, (row.pending / scale) * 100));
      const remaining = hasLimit ? limit - projected : null;
      return <div className="categoryBar" key={row.id}>
        <div className="categoryBarTop">{onSelect ? <button className="categoryNameButton" onClick={() => onSelect(row.id)}>{row.name} <ArrowRight size={13} /></button> : <strong>{row.name}</strong>}<span>{hasLimit ? `${budgetMoney(projected)} / ${budgetMoney(limit)}` : money(projected)}</span></div>
        <div className="categoryProgressRow">
          <div className={`categoryTrack ${hasLimit ? "budgetTrack" : ""}`} role="img" aria-label={hasLimit ? `${row.name}: ${budgetMoney(projected)} of ${budgetMoney(limit)} monthly limit, ${Math.round(progress * 100)} percent${overage > 0 ? `, ${budgetMoney(overage)} over` : ""}` : `${row.name}: ${money(row.posted)} posted, ${money(row.pending)} pending`}>
            {hasLimit ? <>
              <div className="budgetFill" style={{ width: `${Math.min(100, progress * 100)}%` }} />
              {overage > 0 && <div className="budgetOverflow" style={{ width: `${overflowWidth}%` }} />}
            </> : <>
              <div className="categoryPosted" style={{ width: `${postedWidth}%` }} />
              <div className="categoryPending" style={{ width: `${pendingWidth}%` }} />
            </>}
          </div>
          {overage > 0 && <span className="budgetMultiplier">{progress.toFixed(1)}x</span>}
        </div>
        <div className="categoryBarFoot">
          <span>{money(row.posted)} posted{row.pending > 0 ? ` · ${money(row.pending)} pending` : ""}</span>
          <span className={overage > 0 ? "overLimit" : ""}>
            {remaining === null ? (showLimits ? "No limit set" : "") : <>
              {overage > 0 ? `+ ${budgetMoney(overage)} over${accountScoped ? " overall limit" : ""}` : accountScoped ? "Overall limit spans all accounts" : `${budgetMoney(remaining)} left`}
              <span className="budgetPercent">{Math.round(progress * 100)}%</span>
            </>}
          </span>
        </div>
      </div>;
    })}
  </div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="emptyState"><WalletCards size={24} /><strong>{title}</strong><p>{detail}</p></div>;
}

function AccountSelect({ value, accounts, onChange }: {
  value: string; accounts: CanonicalAccount[]; onChange: (value: string) => void;
}) {
  return <label className="accountPicker"><span>Account</span><select value={value} onChange={(event) => onChange(event.target.value)} aria-label="Select account">
    <option value="">All accounts</option>
    {accounts.map((account) => <option key={account.id} value={account.id}>{account.institution_name ? `${account.institution_name} · ` : ""}{account.name}{account.mask ? ` ··${account.mask}` : ""}</option>)}
  </select></label>;
}

export default function App() {
  const [page, setPage] = useState<Page>(() => {
    const hash = window.location.hash.slice(1);
    return isPage(hash) ? hash : "overview";
  });
  const [mobileMenu, setMobileMenu] = useState(false);
  const [month, setMonth] = useState(currentMonth);
  const [accountId, setAccountId] = useState("");
  const [accounts, setAccounts] = useState<CanonicalAccount[]>([]);
  const [reportStart, setReportStart] = useState(reportStartKey);
  const [reportEnd, setReportEnd] = useState(todayKey);
  const [transactionStart, setTransactionStart] = useState("");
  const [transactionEnd, setTransactionEnd] = useState("");
  const [transactionCategory, setTransactionCategory] = useState("");
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [recentTransactions, setRecentTransactions] = useState<Transaction[]>([]);
  const [overviewReport, setOverviewReport] = useState<SpendingReport | null>(null);
  const [rangeReport, setRangeReport] = useState<SpendingReport | null>(null);
  const [limits, setLimits] = useState<MonthlyLimit[]>([]);
  const [goalEvaluations, setGoalEvaluations] = useState<GoalEvaluation[]>([]);
  const [priorGoalEvaluations, setPriorGoalEvaluations] = useState<GoalEvaluation[]>([]);
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
  const [gmailConnections, setGmailConnections] = useState<GmailConnection[]>([]);
  const [selectedTransactionId, setSelectedTransactionId] = useState<string | null>(null);
  const [transactionContext, setTransactionContext] = useState<TransactionContext | null>(null);
  const [orderSearch, setOrderSearch] = useState("");
  const [orderResults, setOrderResults] = useState<OrderSearchResult[]>([]);

  useEffect(() => {
    const onHashChange = () => {
      const hash = window.location.hash.slice(1);
      if (isPage(hash)) setPage(hash);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    const gmailResult = new URLSearchParams(window.location.search).get("gmail");
    if (!gmailResult) return;
    setNotice(gmailResult === "connected" ? "Gmail connected. Sync receipts to import purchase context."
      : gmailResult === "cancelled" ? "Gmail authorization was canceled."
      : "Gmail authorization could not be completed. Try connecting again.");
    window.history.replaceState(null, "", window.location.pathname + window.location.hash);
  }, []);

  const navigate = (next: Page) => {
    window.location.hash = next;
    setPage(next);
    setMobileMenu(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const openCategory = (categoryId: string, startDate: string, endDate: string) => {
    setTransactionCategory(categoryId);
    setTransactionStart(startDate);
    setTransactionEnd(endDate);
    setSearchInput("");
    setSearchQuery("");
    navigate("transactions");
  };

  const refresh = useCallback(async () => {
    const { start, end } = monthRange(month);
    const query = new URLSearchParams({ limit: "100" });
    if (searchQuery) query.set("query", searchQuery);
    if (accountId) query.set("account_id", accountId);
    if (transactionStart) query.set("start_date", transactionStart);
    if (transactionEnd) query.set("end_date", transactionEnd);
    if (transactionCategory) query.set("category_id", transactionCategory);
    const overviewQuery = new URLSearchParams({ start_date: start, end_date: end });
    const reportQuery = new URLSearchParams({ start_date: reportStart, end_date: reportEnd });
    if (accountId) { overviewQuery.set("account_id", accountId); reportQuery.set("account_id", accountId); }
    const recentQuery = new URLSearchParams({ limit: "5" });
    if (accountId) recentQuery.set("account_id", accountId);
    const urls = [
      `/transactions?${query}`, `/analytics/spending-report?${overviewQuery}`,
      `/analytics/spending-report?${reportQuery}`,
      "/budgets/monthly-limits", "/categorization/categories", "/plaid/items",
      "/categorization/jobs?limit=100", "/categorization/summary", `/transactions?${recentQuery}`,
      "/accounts", `/goals/evaluations?month=${month}`,
      `/goals/evaluations?month=${previousMonth(month)}`,
    ];
    try {
      const responses = await Promise.all(urls.map((url) => fetch(`${API_BASE_URL}${url}`)));
      const [nextTransactions, nextOverview, nextRange, nextLimits, nextCategories, nextItems, nextJobs, nextCategorizationSummary, nextRecent, nextAccounts, nextGoals, nextPriorGoals] = await Promise.all([
        readJson<Transaction[]>(responses[0]), readJson<SpendingReport>(responses[1]),
        readJson<SpendingReport>(responses[2]), readJson<MonthlyLimit[]>(responses[3]),
        readJson<Category[]>(responses[4]), readJson<PlaidItem[]>(responses[5]),
        readJson<CategorizationJob[]>(responses[6]), readJson<CategorizationSummary>(responses[7]),
        readJson<Transaction[]>(responses[8]),
        readJson<CanonicalAccount[]>(responses[9]),
        readJson<GoalEvaluation[]>(responses[10]),
        readJson<GoalEvaluation[]>(responses[11]),
      ]);
      setTransactions(nextTransactions);
      setRecentTransactions(nextRecent);
      setOverviewReport(nextOverview);
      setRangeReport(nextRange);
      setLimits(nextLimits);
      setGoalEvaluations(nextGoals);
      setPriorGoalEvaluations(nextPriorGoals);
      setCategories(nextCategories);
      setAccounts(nextAccounts);
      setPlaidItems(nextItems);
      setJobs(nextJobs);
      setCategorizationSummary(nextCategorizationSummary);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Unable to load your data.");
    } finally {
      setLoading(false);
    }
  }, [month, accountId, reportStart, reportEnd, searchQuery, transactionStart, transactionEnd, transactionCategory]);

  useEffect(() => { void refresh(); }, [refresh]);

  const postedOut = Number(overviewReport?.summary.posted_spending ?? 0);
  const pendingOut = Number(overviewReport?.summary.pending_spending ?? 0);
  const postedIn = Number(overviewReport?.summary.posted_money_in ?? 0);
  const pendingIn = Number(overviewReport?.summary.pending_money_in ?? 0);
  const categoryTotals = useMemo(() => {
    return (overviewReport?.categories ?? []).map((row) => ({
      id: row.parent_category_id, name: row.parent_category,
      posted: Number(row.posted_amount), pending: Number(row.pending_amount),
    }));
  }, [overviewReport]);
  const rangeCategories = (rangeReport?.categories ?? []).map((row) => ({
    id: row.parent_category_id, name: row.parent_category,
    posted: Number(row.posted_amount), pending: Number(row.pending_amount),
  }));
  const rangeSummary = rangeReport?.summary;
  const movementOut = Number(overviewReport?.summary.posted_movements_out ?? 0)
    + Number(overviewReport?.summary.pending_movements_out ?? 0);
  const movementIn = Number(overviewReport?.summary.posted_movements_in ?? 0)
    + Number(overviewReport?.summary.pending_movements_in ?? 0);
  const selectedCategoryName = categories.find((category) => category.category_id === transactionCategory)?.display_name ?? transactionCategory;
  const expenseCategories = categories.filter((category) => !["income", "financial"].includes(category.category_id));
  const categoryById = new Map(categoryTotals.map((row) => [row.id, row]));
  const parentGoalById = new Map(goalEvaluations.filter((entry) =>
    entry.goal.scope_kind === "category" && entry.goal.status === "active",
  ).map((entry) => [entry.goal.category_id, entry]));
  const whereRows = expenseCategories.map((category) => ({
    id: category.category_id, name: category.display_name,
    posted: categoryById.get(category.category_id)?.posted ?? 0,
    pending: categoryById.get(category.category_id)?.pending ?? 0,
    goal: parentGoalById.get(category.category_id),
  }));
  const relativeScale = Math.max(1, ...whereRows.map((row) => row.posted + row.pending));

  const runAction = async (action: () => Promise<void>) => {
    setBusy(true);
    try { await action(); } catch (error) {
      setNotice(error instanceof Error ? error.message : "Something went wrong.");
    } finally { setBusy(false); }
  };

  const refreshGmail = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/gmail/status`);
      setGmailConnections(await readJson<GmailConnection[]>(response));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Gmail status is unavailable.");
    }
  }, []);

  useEffect(() => { if (page === "accounts") void refreshGmail(); }, [page, refreshGmail]);
  useEffect(() => {
    if (page === "transactions" && transactionContext) {
      document.querySelector(".receiptDetail")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [page, transactionContext]);

  const openTransaction = (id: string) => void runAction(async () => {
    setSelectedTransactionId(id);
    setTransactionContext(null);
    setOrderResults([]);
    setOrderSearch("");
    setTransactionContext(await readJson<TransactionContext>(
      await fetch(`${API_BASE_URL}/transactions/${id}/context`),
    ));
  });

  const refreshContext = async () => {
    if (!selectedTransactionId) return;
    setTransactionContext(await readJson<TransactionContext>(
      await fetch(`${API_BASE_URL}/transactions/${selectedTransactionId}/context`),
    ));
    await refresh();
  };

  const connectGmail = () => void runAction(async () => {
    const { authorization_url } = await readJson<{ authorization_url: string }>(
      await fetch(`${API_BASE_URL}/gmail/connect`, { method: "POST" }),
    );
    window.location.assign(authorization_url);
  });

  const syncGmail = () => void runAction(async () => {
    const result = await readJson<{ imported: number; skipped: number; failed: number; limited: boolean; reconciliation?: { status?: string; links_created?: number } }>(
      await fetch(`${API_BASE_URL}/gmail/sync`, { method: "POST" }),
    );
    setNotice(`Receipts: ${result.imported} imported, ${result.skipped} already present, ${result.failed} failed.`
      + (result.reconciliation?.status === "failed" ? " Receipt matching needs a retry." : ` ${result.reconciliation?.links_created ?? 0} new receipt links.`)
      + (result.limited ? " Search limit reached; some messages were not checked." : ""));
    await Promise.all([refreshGmail(), refresh()]);
  });

  const disconnectGmail = (id: string, deleteExtracted: boolean) => void runAction(async () => {
    const result = await readJson<{ google_revoked: boolean }>(await fetch(`${API_BASE_URL}/gmail/${id}/disconnect`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ delete_extracted: deleteExtracted }),
    }));
    setNotice((deleteExtracted ? "Gmail disconnected and local receipt records deleted." : "Gmail disconnected; local receipt records retained.")
      + (result.google_revoked ? "" : " Google revocation could not be confirmed; check your Google Account permissions."));
    await Promise.all([refreshGmail(), refresh()]);
  });

  const acceptReceipt = (orderId: string) => void runAction(async () => {
    if (!selectedTransactionId) return;
    await readJson(await fetch(`${API_BASE_URL}/transactions/${selectedTransactionId}/matches`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order_id: orderId }),
    }));
    await refreshContext();
  });

  const unlinkReceipt = (matchId: string) => void runAction(async () => {
    if (!selectedTransactionId) return;
    const response = await fetch(`${API_BASE_URL}/transactions/${selectedTransactionId}/matches/${matchId}`, { method: "DELETE" });
    if (!response.ok) throw new Error("Could not unlink the receipt.");
    await refreshContext();
  });

  const findOrders = (event: FormEvent) => {
    event.preventDefault();
    void runAction(async () => {
      const params = new URLSearchParams({ query: orderSearch.trim() });
      setOrderResults(await readJson<OrderSearchResult[]>(await fetch(`${API_BASE_URL}/receipts/orders?${params}`)));
    });
  };

  const saveItem = (itemId: string, description: string, categoryId: string) => void runAction(async () => {
    await readJson(await fetch(`${API_BASE_URL}/receipts/items/${itemId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description, category_id: categoryId }),
    }));
    await refreshContext();
  });

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
    const result = await readJson<{ items_synced: number; transactions_added: number; receipt_reconciliation?: { status?: string; links_created?: number } }>(await fetch(`${API_BASE_URL}/plaid/sync-transactions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }));
    setNotice(`${result.items_synced} connection synced · ${result.transactions_added} transactions added.`
      + (result.receipt_reconciliation?.status === "failed" ? " Receipt matching needs a retry." : ` ${result.receipt_reconciliation?.links_created ?? 0} new receipt links.`));
    await refresh();
  });

  const connectBank = (existingItemId?: string) => void runAction(async () => {
    await loadPlaidScript();
    const token = await readJson<{ link_token: string }>(await fetch(`${API_BASE_URL}/plaid/link-token`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: existingItemId ?? null }),
    }));
    if (!window.Plaid) throw new Error("Plaid Link could not be started.");
    window.Plaid.create({
      token: token.link_token,
      onSuccess: (publicToken, metadata) => {
        void runAction(async () => {
          let itemId = existingItemId;
          if (!itemId) {
            const connected = await readJson<{ item_id: string }>(await fetch(`${API_BASE_URL}/plaid/exchange-public-token`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ public_token: publicToken, metadata }),
            }));
            itemId = connected.item_id;
          }
          await readJson(await fetch(`${API_BASE_URL}/plaid/sync-transactions`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ item_id: itemId }),
          }));
          setNotice(existingItemId ? "Bank reauthenticated and transactions synced." : "Bank connected and transactions synced.");
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
  const accountSelect = <AccountSelect value={accountId} accounts={accounts} onChange={setAccountId} />;

  return <div className="appShell">
    <aside className={`sidebar ${mobileMenu ? "sidebarOpen" : ""}`}>
      <div className="brand"><div className="brandMark"><WalletCards size={20} /></div><div><strong>Finance Guardian</strong><span>Personal finance</span></div></div>
      <div className="navLabel">WORKSPACE</div>
      <nav aria-label="Main navigation">
        <button className={page === "overview" ? "navItem active" : "navItem"} onClick={() => navigate("overview")} aria-current={page === "overview" ? "page" : undefined}><LayoutDashboard size={18} />Overview</button>
        <button className={page === "transactions" ? "navItem active" : "navItem"} onClick={() => navigate("transactions")} aria-current={page === "transactions" ? "page" : undefined}><List size={18} />Transactions</button>
        <button className={page === "reports" ? "navItem active" : "navItem"} onClick={() => navigate("reports")} aria-current={page === "reports" ? "page" : undefined}><ChartNoAxesCombined size={18} />Reports</button>
        <button className={page === "intelligence" ? "navItem active" : "navItem"} onClick={() => navigate("intelligence")} aria-current={page === "intelligence" ? "page" : undefined}><Sparkles size={18} />Intelligence</button>
        <button className={page === "goals" ? "navItem active" : "navItem"} onClick={() => navigate("goals")} aria-current={page === "goals" ? "page" : undefined}><WalletCards size={18} />Goals</button>
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
        <div className="pageHeading"><div><div className="eyebrow">OVERVIEW</div><h1>Financial overview</h1><p>Spending and money in, with transfers and card payments tracked separately.</p></div><div className="headingFilters">{accountSelect}{monthSelect}</div></div>
        {!loading && accounts.length === 0 && <div className="welcomeBanner"><div><strong>Start with your transactions</strong><p>Connect a bank or upload a statement to see your cash flow and spending patterns.</p></div><button className="primaryButton" onClick={() => navigate("accounts")}>Go to accounts <ArrowRight size={16} /></button></div>}
        <section className="summaryGrid" aria-label="Cash flow summary">
          <SummaryCard label="Spending" posted={postedOut} pending={pendingOut} tone="out" note="Movements excluded" />
          <SummaryCard label="Money in" posted={postedIn} pending={pendingIn} tone="in" note="Includes refunds" />
          <SummaryCard label="Net flow" posted={postedIn - postedOut} pending={pendingIn - pendingOut} tone="net" note="Excludes movements" />
        </section>
        {(movementOut > 0 || movementIn > 0) && <p className="movementNote">{money(movementOut)} moved out and {money(movementIn)} moved in through transfers or card payments. These are shown in Transactions and excluded from spending and net flow.</p>}
        <div className="dashboardGrid">
          <section className="surface trendPanel"><div className="sectionTitle"><div><span className="eyebrow">THE BIG PICTURE</span><h2>Money in vs. spending</h2></div><span className="sectionHint">Report date range</span></div><TrendChart rows={rangeReport?.months ?? []} /></section>
        </div>
        <section className="surface categoryPanel"><div className="sectionTitle"><div><span className="eyebrow">WHERE IT WENT</span><h2>Every spending category</h2></div><button className="textButton" onClick={() => navigate("goals")}>Manage goals <ArrowRight size={15} /></button></div>
          <p className="sectionDescription">The fill rises from the bottom. Goal tiles use projected net spend, including pending activity; tiles without a goal show relative category spending.{accountId ? " Goals always use all accounts." : ""} Scroll to see all categories.</p>
          <div className="whereTiles" aria-label="Monthly spending by category">{whereRows.map((row) => {
            const goal = row.goal;
            const range = monthRange(month);
            return <CategoryFillTile key={row.id} name={row.name}
              posted={goal ? Number(goal.posted_spend) : row.posted}
              pending={goal ? Number(goal.pending_net) : row.pending}
              limit={goal ? Number(goal.threshold_amount) : undefined}
              currency={goal?.currency ?? "USD"} relativeScale={relativeScale}
              onClick={() => openCategory(row.id, range.start, range.end)} />;
          })}</div>
        </section>
        <section className="surface recentPanel"><div className="sectionTitle"><div><span className="eyebrow">LATEST ACTIVITY</span><h2>Recent transactions</h2></div><button className="textButton" onClick={() => navigate("transactions")}>View all <ArrowRight size={15} /></button></div><TransactionList rows={recentTransactions} compact /></section>
      </>}

      {page === "goals" && <GoalsPage evaluations={goalEvaluations} priorEvaluations={priorGoalEvaluations} categories={categories} month={month}
        onMonthChange={setMonth} onRefresh={refresh}
        onTransaction={(id) => { navigate("transactions"); openTransaction(id); }} />}

      {page === "intelligence" && <>
        <div className="pageHeading"><div><div className="eyebrow">INTELLIGENCE</div><h1>Explain my spending</h1><p>See which purchases changed your spending between two periods.</p></div>{accountSelect}</div>
        <ExplainSpendingPage apiBaseUrl={API_BASE_URL} accountId={accountId}
          onTransaction={(id) => { navigate("transactions"); openTransaction(id); }} />
        <RecurringChargesPanel apiBaseUrl={API_BASE_URL} accountId={accountId}
          accountNames={new Map(accounts.map((account) => [account.id, account.name]))}
          onTransaction={(id) => { navigate("transactions"); openTransaction(id); }} />
        <AnomalyPanel apiBaseUrl={API_BASE_URL} accountId={accountId}
          onTransaction={(id) => { navigate("transactions"); openTransaction(id); }} />
        <BehavioralAlertsPanel apiBaseUrl={API_BASE_URL} accountId={accountId}
          onTransaction={(id) => { navigate("transactions"); openTransaction(id); }} />
        <ForecastPanel apiBaseUrl={API_BASE_URL} accountId={accountId}
          categories={categories.flatMap((category) => [
            { id: category.category_id, name: category.display_name },
            ...category.subcategories.map((sub) => ({ id: sub.category_id, name: `${category.display_name} / ${sub.display_name}` })),
          ])} />
      </>}

      {page === "transactions" && <>
        <div className="pageHeading"><div><div className="eyebrow">ACTIVITY</div><h1>Transactions</h1><p>Find activity and keep categories accurate.</p></div>{accountSelect}</div>
        <div className="transactionFilters"><label>From<input type="date" value={transactionStart} max={transactionEnd || undefined} onChange={(event) => setTransactionStart(event.target.value)} /></label><label>To<input type="date" value={transactionEnd} min={transactionStart || undefined} onChange={(event) => setTransactionEnd(event.target.value)} /></label><label>Category<select value={transactionCategory} onChange={(event) => setTransactionCategory(event.target.value)}><option value="">All categories</option>{categories.map((category) => <option key={category.category_id} value={category.category_id}>{category.display_name}</option>)}</select></label>{(transactionStart || transactionEnd || transactionCategory) && <button className="textButton" onClick={() => { setTransactionStart(""); setTransactionEnd(""); setTransactionCategory(""); }}>Clear activity filters</button>}</div>
        {transactionCategory && <p className="filterContext">Showing {selectedCategoryName} transactions. Category changes here update your reports.</p>}
        <section className="surface"><form className="searchBar" onSubmit={(event) => { event.preventDefault(); setSearchQuery(searchInput.trim()); }}><Search size={18} /><input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search merchant or description" aria-label="Search transactions" /><button className="primaryButton" type="submit">Search</button>{searchQuery && <button className="textButton" type="button" onClick={() => { setSearchInput(""); setSearchQuery(""); }}>Clear</button>}</form><div className="tableWrap"><table className="transactionTable"><thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Receipt</th><th>Account</th><th className="amountCell">Amount</th></tr></thead><tbody>{transactions.map((transaction) => <tr key={transaction.id}><td>{transaction.posted_date}</td><td><button className="transactionOpen" onClick={() => openTransaction(transaction.id)}>{transaction.canonical_merchant_name ?? transaction.description}</button><small>{transaction.is_pending ? "Pending" : "Posted"}</small></td><td><select aria-label={`Category for ${transaction.description}`} value={transaction.subcategory_id ?? ""} onChange={(event) => updateCategory(transaction.id, event.target.value)} disabled={busy}><option value="">Uncategorized</option>{categories.map((category) => <optgroup key={category.category_id} label={category.display_name}>{category.subcategories.map((sub) => <option key={sub.category_id} value={sub.category_id}>{sub.display_name}</option>)}</optgroup>)}</select></td><td><span className={`receiptBadge ${transaction.receipt_status}`}>{transaction.receipt_status === "matched" ? "Receipt matched" : transaction.receipt_status === "possible" ? "Possible match" : "No receipt"}</span></td><td>{transaction.account_name}</td><td className={`amountCell ${transaction.direction === "credit" ? "positive" : ""}`}>{transaction.direction === "credit" ? "+" : "−"}{money(Number(transaction.amount))}</td></tr>)}</tbody></table>{transactions.length === 0 && <EmptyState title={searchQuery ? "No matching transactions" : "No transactions yet"} detail={searchQuery ? "Try a different search." : "Connect a bank or import a statement to get started."} />}</div></section>
      </>}

      {page === "transactions" && transactionContext && <TransactionDetail
        context={transactionContext} orders={orderResults} orderSearch={orderSearch}
        categories={categories}
        setOrderSearch={setOrderSearch} onSearch={findOrders}
        onClose={() => { setSelectedTransactionId(null); setTransactionContext(null); }}
        onAccept={acceptReceipt} onUnlink={unlinkReceipt} onSaveItem={saveItem} busy={busy}
      />}

      {page === "reports" && <>
        <div className="pageHeading"><div><div className="eyebrow">PATTERNS</div><h1>Reports</h1><p>Explore spending by account, category, and time. Transfers and card payments are excluded.</p></div>{accountSelect}</div>
        <div className="reportFilters"><label>From<input type="date" value={reportStart} max={reportEnd} onChange={(event) => { if (event.target.value) setReportStart(event.target.value); }} /></label><label>To<input type="date" value={reportEnd} min={reportStart} max={todayKey()} onChange={(event) => { if (event.target.value) setReportEnd(event.target.value); }} /></label><span>All charts below use this date range and account.</span></div>
        <div className="reportSummary"><div className="reportMetric"><span>Posted spending</span><strong>{money(Number(rangeSummary?.posted_spending ?? 0))}</strong></div><div className="reportMetric"><span>Posted money in</span><strong>{money(Number(rangeSummary?.posted_money_in ?? 0))}</strong></div><div className="reportMetric"><span>Posted net flow</span><strong>{money(Number(rangeSummary?.posted_money_in ?? 0) - Number(rangeSummary?.posted_spending ?? 0))}</strong></div></div>
        <section className="surface reportTrend"><div className="sectionTitle"><div><span className="eyebrow">MONTH BY MONTH</span><h2>Money in vs. spending</h2></div></div><TrendChart rows={rangeReport?.months ?? []} /></section>
        {rangeReport && <div className="reportVisualGrid"><section className="surface"><div className="sectionTitle"><div><span className="eyebrow">CATEGORY TRENDS</span><h2>How spending changed</h2></div></div><p className="sectionDescription">Posted spending by month. Select a segment to see its transactions.</p><CategoryTrend report={rangeReport} onSelect={(id, selectedMonth) => { const range = selectedMonth ? monthRange(selectedMonth) : { start: reportStart, end: reportEnd }; openCategory(id, range.start < reportStart ? reportStart : range.start, range.end > reportEnd ? reportEnd : range.end); }} /></section><section className="surface"><div className="sectionTitle"><div><span className="eyebrow">CATEGORY SHARE</span><h2>Where spending went</h2></div></div><p className="sectionDescription">Share of posted spending in the selected range.</p><CategoryShare report={rangeReport} onSelect={(id) => openCategory(id, reportStart, reportEnd)} /></section></div>}
        <section className="surface"><div className="sectionTitle"><div><span className="eyebrow">SPENDING DETAIL</span><h2>Categories in this range</h2></div></div><p className="sectionDescription">Posted and pending amounts are separate. Budgets remain global across all accounts.</p><CategoryBars rows={rangeCategories} limits={limits} showLimits={false} onSelect={(id) => openCategory(id, reportStart, reportEnd)} /></section>
      </>}

      {page === "accounts" && <>
        <div className="pageHeading"><div><div className="eyebrow">DATA SOURCES</div><h1>Accounts & connections</h1><p>Manage connected institutions and keep transaction data fresh.</p></div></div>
        <div className="accountActions"><button className="primaryButton" onClick={() => connectBank()} disabled={busy}><Building2 size={17} />Connect bank</button><button className="secondaryButton" onClick={syncBanks} disabled={busy || plaidItems.length === 0}><RefreshCw size={17} />Sync transactions</button></div>
        <section className="surface"><div className="sectionTitle"><div><span className="eyebrow">CONNECTED</span><h2>Institutions</h2></div><span className="sectionHint">{plaidItems.length} connected</span></div>{plaidItems.length === 0 ? <EmptyState title="No bank connections" detail="Connect a bank to bring your accounts and transactions together." /> : <div className="institutionList">{plaidItems.map((item) => <div className="institution" key={item.item_id}><div className="institutionHead"><div className="institutionIcon"><Building2 size={21} /></div><div><strong>{item.institution_name ?? "Connected institution"}</strong><span>{item.accounts.length} accounts{!item.has_cursor ? " · sync needed" : ""}</span></div><span className="connectionStatus"><Check size={14} />{item.status}</span><button className="textButton" onClick={() => connectBank(item.item_id)} disabled={busy}>Reauthenticate</button></div>{item.accounts.map((account) => <div className="accountRow" key={account.account_id}><span>{account.name}{account.mask ? ` ····${account.mask}` : ""}</span><strong>{account.current_balance === null ? "Balance unavailable" : money(Number(account.current_balance))}</strong></div>)}</div>)}</div>}</section>
        <section className="surface gmailPanel">
          <div className="sectionTitle"><div><span className="eyebrow">PURCHASE CONTEXT</span><h2>Gmail receipts</h2></div><span className="sectionHint">{gmailConnections.some((connection) => connection.status === "active") ? "Connected" : "Not connected"}</span></div>
          <p className="sectionDescription">Google's read-only Gmail permission can read messages and settings across your mailbox. Guardian currently searches recent Uber Eats order emails and stores extracted order details locally. Some emails include only a total, so missing items and fees stay unknown.</p>
          {gmailConnections.some((connection) => connection.status === "demo")
            ? <p className="sectionDescription">Synthetic demo receipts are loaded locally. No Gmail account is connected.</p>
            : <div className="inlineActions"><button className="primaryButton" onClick={connectGmail} disabled={busy}>Connect Gmail</button><button className="secondaryButton" onClick={syncGmail} disabled={busy || !gmailConnections.some((connection) => connection.status === "active")}><RefreshCw size={16} />Sync receipts</button></div>}
          {gmailConnections.map((connection) => <div className="gmailConnection" key={connection.id}>
            <div><strong>{connection.email_address}</strong><span>{connection.status} · {connection.source_count} local messages · Last sync {connection.last_sync_at ? new Date(connection.last_sync_at).toLocaleString() : "Never"}</span>{connection.last_run && <small>Last import: {connection.last_run.imported} new, {connection.last_run.skipped} already present, {connection.last_run.failed} failed.</small>}</div>
            {connection.status === "disconnected" && connection.source_count > 0
              ? <button className="textButton dangerLink" onClick={() => disconnectGmail(connection.id, true)} disabled={busy}>Delete retained records</button>
              : connection.status !== "demo" && connection.status !== "disconnected"
                ? <div className="inlineActions"><button className="textButton" onClick={() => disconnectGmail(connection.id, false)} disabled={busy}>Disconnect, keep records</button><button className="textButton dangerLink" onClick={() => disconnectGmail(connection.id, true)} disabled={busy}>Disconnect, delete records</button></div>
                : null}
          </div>)}
        </section>
        <section className="surface importPanel"><div><div className="eyebrow">SUPPLEMENTAL HISTORY</div><h2>Import a statement</h2><p>Upload a Chase PDF statement to add transactions that are not yet available through your bank connection.</p></div><label className="secondaryButton uploadButton"><FileUp size={17} />Choose PDF<input type="file" accept="application/pdf" onChange={uploadStatement} disabled={busy} /></label></section>
      </>}

      {page === "settings" && <>
        <div className="pageHeading"><div><div className="eyebrow">PREFERENCES</div><h1>Settings</h1><p>Manage monthly goals, quick limits, and transaction categories.</p></div></div>
        <section className="surface"><div className="sectionTitle"><div><span className="eyebrow">MONTHLY PLANNING</span><h2>Category limits</h2></div></div><p className="sectionDescription">Quick limits are monthly goals. Choose a category or subcategory; the Goals page shows posted progress, pending exposure, and transaction evidence.</p><form className="limitForm" onSubmit={saveLimit}><label>Category<select value={limitCategory} onChange={(event) => { const id = event.target.value; setLimitCategory(id); setLimitAmount(limits.find((limit) => limit.category_id === id)?.amount ?? ""); }} required><option value="">Choose a category</option>{expenseCategories.map((category) => <Fragment key={category.category_id}><option value={category.category_id}>{category.display_name} ? all subcategories</option><optgroup label={category.display_name}>{category.subcategories.map((child) => <option key={child.category_id} value={child.category_id}>{child.display_name}</option>)}</optgroup></Fragment>)}</select></label><label>Monthly limit<input type="number" min="0.01" step="0.01" placeholder="0.00" value={limitAmount} onChange={(event) => setLimitAmount(event.target.value)} required /></label><button className="primaryButton" type="submit" disabled={busy}>Save limit</button></form>{limits.length > 0 && <div className="limitList">{limits.map((limit) => <div className="limitRow" key={limit.category_id}><span>{categories.find((category) => category.category_id === limit.category_id)?.display_name ?? categories.flatMap((category) => category.subcategories).find((child) => child.category_id === limit.category_id)?.display_name ?? limit.category_id}</span><strong>{money(Number(limit.amount))} / month</strong><button className="iconButton subtleButton" onClick={() => removeLimit(limit.category_id)} aria-label={`Remove limit for ${limit.category_id}`} disabled={busy}><Trash2 size={16} /></button></div>)}</div>}</section>
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

function EditableReceiptItem({ item, categories, onSave }: {
  item: OrderItem; categories: Category[];
  onSave: (id: string, description: string, categoryId: string) => void;
}) {
  const [description, setDescription] = useState(item.description);
  const [categoryId, setCategoryId] = useState(item.category_id ?? "");
  useEffect(() => { setDescription(item.description); setCategoryId(item.category_id ?? ""); }, [item.description, item.category_id]);
  return <form className="receiptItem" onSubmit={(event) => { event.preventDefault(); onSave(item.id, description.trim(), categoryId.trim()); }}>
    <div className="receiptItemMain">
      <input aria-label="Item description" value={description} onChange={(event) => setDescription(event.target.value)} required />
      <span>Qty {item.quantity ?? "Unknown"} · line total {item.line_total ?? "Unknown"}</span>
    </div>
    <div className="receiptItemMeta">
      <label>Item category <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}><option value="">Unknown</option>{categories.map((category) => <optgroup key={category.category_id} label={category.display_name}>{category.subcategories.map((sub) => <option key={sub.category_id} value={sub.category_id}>{sub.display_name}</option>)}</optgroup>)}</select></label>
      <button type="submit" className="textButton">Save correction</button>
    </div>
    {item.evidence && <small>Source: {item.evidence}</small>}
  </form>;
}

function TransactionDetail({ context, orders, orderSearch, setOrderSearch, categories, onSearch, onClose,
  onAccept, onUnlink, onSaveItem, busy }: {
  context: TransactionContext; orders: OrderSearchResult[]; categories: Category[];
  orderSearch: string; setOrderSearch: (value: string) => void;
  onSearch: (event: FormEvent) => void; onClose: () => void;
  onAccept: (orderId: string) => void; onUnlink: (matchId: string) => void;
  onSaveItem: (id: string, description: string, categoryId: string) => void;
  busy: boolean;
}) {
  return <section className="surface receiptDetail" aria-label="Transaction details">
    <div className="sectionTitle"><div><span className="eyebrow">TRANSACTION CONTEXT</span><h2>{context.transaction.merchant}</h2></div><button className="iconButton" onClick={onClose} aria-label="Close transaction details"><X size={16} /></button></div>
    <div className="receiptFacts">
      <span>Bank amount <strong>{context.transaction.currency ?? "Currency unknown"} {context.transaction.amount}</strong></span>
      <span>Posted <strong>{context.transaction.posted_date}</strong></span>
      <span>State <strong>{context.transaction.is_pending ? "Pending" : "Posted"}</strong></span>
      <span>Account <strong>{context.transaction.account_name}</strong></span>
    </div>
    {context.matches.length === 0 && <EmptyState title="No receipt linked" detail="This transaction still counts in your spending. A receipt may be unavailable or not yet imported." />}
    {context.matches.map((match) => <article className="receiptOrder" key={match.match_id}>
      <div className="receiptOrderHead"><div><span className={`receiptBadge ${match.status}`}>{match.status === "confirmed" ? "Receipt matched" : "Possible match"}</span><h3>{match.order.merchant}{match.order.merchant_order_id ? ` · Order ${match.order.merchant_order_id}` : ""}</h3></div><strong>{match.order.currency ?? "Currency unknown"} {match.order.total ?? "Total unknown"}</strong></div>
      <p className="sectionDescription">Match evidence: {match.reasons.join(", ")}. Confidence {Math.round(Number(match.confidence) * 100)}%.</p>
      <div className="receiptFacts"><span>Order date <strong>{match.order.placed_date ?? "Unknown"}</strong></span><span>Extraction <strong>{match.order.parse_quality}</strong></span></div>
      <h4>Items</h4>
      {match.order.items.length ? match.order.items.map((item) => <EditableReceiptItem key={item.id} item={item} categories={categories} onSave={onSaveItem} />) : <p className="sectionDescription">Items unknown.</p>}
      <div className="receiptCharges">{(["subtotal", "delivery_fee", "tax", "tip", "other_fees", "discount"] as const).map((key) =>
        <span key={key}>{key.replace(/_/g, " ")} <strong>{match.order[key] ?? "Unknown"}</strong></span>,
      )}</div>
      {match.order.source && <p className="receiptSource">Source: {match.order.source.sender ?? "Unknown sender"} · {match.order.source.subject ?? "Unknown subject"} · received {match.order.source.received_at ?? "Unknown"} · message {match.order.source.message_id}</p>}
      <div className="inlineActions">{match.status === "suggested" && <button className="primaryButton" onClick={() => onAccept(match.order.id)} disabled={busy}>Accept match</button>}<button className="secondaryButton" onClick={() => onUnlink(match.match_id)} disabled={busy}>Unlink</button></div>
    </article>)}
    <form className="receiptSearch" onSubmit={onSearch}><label>Find another imported order<input value={orderSearch} onChange={(event) => setOrderSearch(event.target.value)} placeholder="Merchant name" /></label><button className="secondaryButton" type="submit" disabled={busy}>Search orders</button></form>
    {orders.length > 0 && <div className="receiptResults">{orders.map((order) => <div key={order.id}><span>{order.merchant} · {order.placed_date ?? "Date unknown"} · {order.currency ?? "Currency unknown"} {order.total ?? "Total unknown"}</span><button className="textButton" onClick={() => onAccept(order.id)} disabled={busy}>Link</button></div>)}</div>}
  </section>;
}
