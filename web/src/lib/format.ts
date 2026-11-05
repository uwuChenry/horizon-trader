export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function pct(v: unknown, digits = 1, sign = false): string {
  if (!isNum(v)) return "–";
  const s = (v * 100).toFixed(digits) + "%";
  return sign && v > 0 ? "+" + s : s;
}

export function money(v: unknown, opts: { sign?: boolean; cents?: boolean } = {}): string {
  if (!isNum(v)) return "–";
  const cents = opts.cents ?? Math.abs(v) < 100;
  const s = Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  });
  const sign = v < 0 ? "-" : opts.sign && v > 0 ? "+" : "";
  return `${sign}$${s}`;
}

export function fixed(v: unknown, digits = 2, sign = false): string {
  if (!isNum(v)) return "–";
  const s = v.toFixed(digits);
  return sign && v > 0 ? "+" + s : s;
}

export function int(v: unknown): string {
  if (!isNum(v)) return "–";
  return Math.round(v).toLocaleString("en-US");
}

export function compact(v: unknown): string {
  if (!isNum(v)) return "–";
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

export function bytes(v: number | null): string {
  if (v === null) return "";
  if (v < 1024) return `${v} B`;
  if (v < 1024 ** 2) return `${(v / 1024).toFixed(0)} KB`;
  return `${(v / 1024 ** 2).toFixed(1)} MB`;
}

/** Stats keys -> how to show them (mirrors the old dashboard's PCT/MONEY sets). */
const PCT = new Set([
  "total return", "CAGR", "vol", "max DD", "best day", "worst day", "% up days", "win rate",
  "costs / gross profit", "best 5% share of P&L", "% long", "alpha/yr",
]);
const MONEY = new Set([
  "start equity", "end equity", "total P&L", "avg win", "avg loss", "expectancy $", "largest win",
  "largest loss", "gross P&L", "costs",
]);

export function stat(key: string, v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (!isNum(v)) return String(v);
  if (PCT.has(key)) return pct(v);
  if (MONEY.has(key)) return money(v);
  if (Number.isInteger(v)) return int(v);
  return fixed(v);
}

export const tone = (v: unknown) => (!isNum(v) || v === 0 ? "" : v > 0 ? "text-pos" : "text-neg");

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  return iso.slice(0, 10);
}

/** ISO timestamp -> HH:MM in New York, for intraday tables. */
export function nyTime(iso: unknown): string {
  if (typeof iso !== "string") return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "America/New_York",
  });
}

export function cellText(col: string, v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") {
    if (/^\d{4}-\d{2}-\d{2}T00:00:00(\.000)?$/.test(v)) return v.slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}T/.test(v)) return v.slice(0, 16).replace("T", " ");
    return v;
  }
  if (isNum(v)) {
    if (/(^|_|\s)(pct|weight|return|CAGR|DD|vol|rate|share)(\b|_|$)/i.test(col) && Math.abs(v) < 20)
      return pct(v);
    if (Number.isInteger(v)) return Math.abs(v) >= 10000 ? int(v) : String(v);
    const a = Math.abs(v);
    return v.toFixed(a >= 1000 ? 0 : a >= 1 ? 2 : 4);
  }
  return String(v);
}
