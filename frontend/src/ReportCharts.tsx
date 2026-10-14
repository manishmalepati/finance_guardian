export type ReportSummary = {
  posted_spending: number;
  pending_spending: number;
  posted_money_in: number;
  pending_money_in: number;
  posted_movements_out: number;
  pending_movements_out: number;
  posted_movements_in: number;
  pending_movements_in: number;
};

export type ReportMonth = ReportSummary & { month: string };
export type ReportCategory = {
  parent_category_id: string;
  parent_category: string;
  posted_amount: number;
  pending_amount: number;
};
export type ReportCategoryMonth = ReportCategory & { month: string };
export type SpendingReport = {
  start_date: string;
  end_date: string;
  account_id: string | null;
  summary: ReportSummary;
  months: ReportMonth[];
  categories: ReportCategory[];
  category_months: ReportCategoryMonth[];
};

const colors = ["#6bd4d2", "#83aef1", "#e99baa", "#d9b981", "#9f9ae8", "#52728f"];
const money = (value: number) => new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 2,
}).format(value);

function categoryGroups(report: SpendingReport) {
  const ranked = [...report.categories].sort((a, b) => b.posted_amount - a.posted_amount);
  const top = ranked.slice(0, 5);
  const rest = ranked.slice(5);
  return [
    ...top.map((row, index) => ({ id: row.parent_category_id, name: row.parent_category, value: row.posted_amount, color: colors[index] })),
    ...(rest.length ? [{ id: "", name: "Other categories", value: rest.reduce((sum, row) => sum + row.posted_amount, 0), color: colors[5] }] : []),
  ].filter((row) => row.value > 0);
}

function monthKeys(start: string, end: string) {
  const keys: string[] = [];
  const cursor = new Date(`${start.slice(0, 7)}-01T00:00:00Z`);
  const last = end.slice(0, 7);
  while (cursor.toISOString().slice(0, 7) <= last) {
    keys.push(cursor.toISOString().slice(0, 7));
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  return keys;
}

export function CategoryTrend({ report, onSelect }: {
  report: SpendingReport;
  onSelect: (categoryId: string, month: string) => void;
}) {
  const groups = categoryGroups(report);
  const keys = monthKeys(report.start_date, report.end_date);
  const byMonth = new Map<string, Map<string, number>>();
  for (const row of report.category_months) {
    const key = row.month.slice(0, 7);
    const values = byMonth.get(key) ?? new Map<string, number>();
    values.set(row.parent_category_id, row.posted_amount);
    byMonth.set(key, values);
  }
  const topIds = new Set(groups.filter((group) => group.id).map((group) => group.id));
  const entries = keys.map((key) => {
    const values = byMonth.get(key) ?? new Map<string, number>();
    const total = [...values.values()].reduce((sum, amount) => sum + amount, 0);
    return { key, values, total };
  });
  const max = Math.max(1, ...entries.map((entry) => entry.total));

  if (groups.length === 0) return <div className="chartEmpty">No posted spending in this date range.</div>;
  return <div className="stackedChart">
    <div className="stackedScroll"><div className="stackedPlot" style={{ minWidth: `${Math.max(420, entries.length * 68)}px` }}>
      <div className="stackedBars">{entries.map(({ key, values, total }) => {
        const other = [...values].filter(([id]) => !topIds.has(id)).reduce((sum, [, amount]) => sum + amount, 0);
        return <div className="stackedColumn" key={key}>
          <div className="stackedValue">{total > 0 ? money(total) : ""}</div>
          <div className="stackedTrack" aria-label={`${key}: ${money(total)} posted spending`}>
            {groups.map((group) => {
              const value = group.id ? (values.get(group.id) ?? 0) : other;
              if (!value) return null;
              const style = { height: `${(value / max) * 100}%`, backgroundColor: group.color };
              return group.id
                ? <button key={group.name} className="stackedSegment" style={style} title={`${group.name}: ${money(value)}`} aria-label={`${group.name}, ${money(value)} in ${key}; view transactions`} onClick={() => onSelect(group.id, key)} />
                : <div key={group.name} className="stackedSegment" style={style} title={`${group.name}: ${money(value)}`} />;
            })}
          </div>
          <span className="stackedMonth">{new Intl.DateTimeFormat("en-US", { month: "short", year: "2-digit", timeZone: "UTC" }).format(new Date(`${key}-01T00:00:00Z`))}</span>
        </div>;
      })}</div>
    </div></div>
    <div className="chartKey">{groups.map((group) => group.id
      ? <button key={group.name} onClick={() => onSelect(group.id, "")}><span style={{ backgroundColor: group.color }} />{group.name}</button>
      : <span key={group.name}><span style={{ backgroundColor: group.color }} />{group.name}</span>)}</div>
  </div>;
}

export function CategoryShare({ report, onSelect }: {
  report: SpendingReport;
  onSelect: (categoryId: string) => void;
}) {
  const groups = categoryGroups(report);
  const total = groups.reduce((sum, group) => sum + group.value, 0);
  if (!total) return <div className="chartEmpty">No posted spending in this date range.</div>;
  const circumference = 2 * Math.PI * 72;
  let offset = 0;
  return <div className="shareLayout">
    <div className="donutWrap"><svg viewBox="0 0 200 200" role="img" aria-label="Posted spending share by category">
      <circle cx="100" cy="100" r="72" fill="none" stroke="#294764" strokeWidth="24" />
      {groups.map((group) => {
        const length = circumference * (group.value / total);
        const start = offset;
        offset += length;
        return <circle key={group.name} cx="100" cy="100" r="72" fill="none" stroke={group.color} strokeWidth="24"
          strokeDasharray={`${Math.max(0, length - 2)} ${circumference - Math.max(0, length - 2)}`}
          strokeDashoffset={-start} transform="rotate(-90 100 100)" className={group.id ? "donutSlice" : ""}
          onClick={group.id ? () => onSelect(group.id) : undefined}>
          <title>{group.name}: {money(group.value)}</title>
        </circle>;
      })}
    </svg><div className="donutCenter"><strong>{money(total)}</strong><span>posted spending</span></div></div>
    <div className="shareLegend">{groups.map((group) => <button key={group.name} type="button" disabled={!group.id} onClick={() => group.id && onSelect(group.id)}>
      <span className="shareSwatch" style={{ backgroundColor: group.color }} />
      <span className="shareName">{group.name}</span>
      <strong>{Math.round((group.value / total) * 100)}%</strong>
    </button>)}</div>
  </div>;
}
