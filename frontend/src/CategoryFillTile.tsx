import type { CSSProperties } from "react";

const money = (value: number, currency: string) => new Intl.NumberFormat("en-US", {
  style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 2,
}).format(value);

export function CategoryFillTile({ name, posted, pending, limit, currency = "USD", paused = false,
  relativeScale = 0, onClick, large = false }: {
  name: string; posted: number; pending: number; limit?: number; currency?: string;
  paused?: boolean; relativeScale?: number; onClick?: () => void; large?: boolean;
}) {
  const projected = Math.max(0, posted + pending);
  const hasLimit = limit !== undefined && limit > 0 && !paused;
  const fillPercent = hasLimit ? Math.min(100, Math.max(0, projected / limit * 100))
    : relativeScale > 0 ? Math.min(100, Math.max(0, projected / relativeScale * 100)) : 0;
  const over = hasLimit && projected > limit;
  const postedOver = hasLimit && posted > limit;
  const style = { "--fill-percent": `${fillPercent}%` } as CSSProperties;
  const label = hasLimit
    ? `${name}: ${money(posted, currency)} posted, ${money(pending, currency)} pending, ${money(limit, currency)} monthly goal${over ? ", projected over goal" : ""}`
    : `${name}: ${money(projected, currency)} projected spending, no active monthly goal`;
  const inner = <>
    <div className={`fillVessel${over ? " over" : ""}${paused ? " paused" : ""}`} style={style} role="img" aria-label={label}>
      <span className="fillLiquid" aria-hidden="true" />
      <span className="fillName fillNameBase" aria-hidden="true">{name}</span>
      <span className="fillName fillNameInside" aria-hidden="true">{name}</span>
      {over && <span className="fillAlert" aria-hidden="true">!</span>}
    </div>
    <div className="fillTileCaption">
      <strong>{hasLimit ? `${money(projected, currency)} / ${money(limit, currency)}` : money(projected, currency)}</strong>
      <span className={over ? "fillOverText" : ""}>{hasLimit
        ? over ? `${postedOver ? "Over" : "Projected over"} by ${money(projected - limit, currency)}`
          : `${money(Math.max(0, limit - projected), currency)} left`
        : paused ? "Goal paused" : "No monthly goal"}</span>
    </div>
  </>;
  return onClick ? <button type="button" className={`fillTile${large ? " large" : ""}`} onClick={onClick}>{inner}</button>
    : <div className={`fillTile${large ? " large" : ""}`}>{inner}</div>;
}
