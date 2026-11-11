import { useQuery } from "@tanstack/react-query";

export type Point = { t: number; v: number };
export type Table = { columns: string[]; rows: unknown[][]; total: number };
export type Status =
  | "core"
  | "candidate"
  | "running"
  | "inconclusive"
  | "idea"
  | "reference"
  | "dead";

export type StudySummary = {
  id: string;
  slug: string;
  parent: string | null;
  name: string;
  kind: string;
  status: Status;
  verdict: string;
  tags: string[];
  start: string;
  end: string;
  updated: string;
  children?: string[];
};

export type Artifact = {
  ref: string;
  label: string;
  role: string;
  suffix: string;
  bytes: number | null;
};

export type Study = Omit<StudySummary, "children"> & {
  description: string;
  code: string[];
  report: { ref: string; markdown: string } | null;
  docs: { ref: string; name: string; title: string }[];
  artifacts: Artifact[];
  children: StudySummary[];
};

export type Doc = { ref: string; title: string; markdown: string; study: string | null };

export type RunRow = {
  run_id: string;
  name: string;
  strategy: string | null;
  created: string;
  start: string;
  end: string;
  holdings: boolean;
  CAGR?: number | null;
  Sharpe?: number | null;
  "max DD"?: number | null;
  trades?: number;
};

export type Stats = Record<string, number | null>;

export type RunDetail = {
  run_id: string;
  meta: {
    name?: string;
    strategy?: string;
    created?: string;
    start?: string;
    end?: string;
    git_commit?: string;
    git_dirty?: boolean;
    caveats?: string[];
    params?: Record<string, unknown>;
    benchmark?: string;
    oos_start?: string;
    costs_description?: string;
    chart?: string;
    how_it_works?: string;
  };
  stats: Stats;
  trade_stats: Stats;
  equity: Point[];
  benchmark: Point[];
  drawdown: Point[];
  monthly: { months: string[]; rows: { year: number; values: (number | null)[]; total: number | null }[] };
  rolling_sharpe: Record<string, Point[]>;
  daily_hist: { edges: number[]; counts: number[] };
  drawdowns: Table;
  holdings: boolean;
  trades: number;
  costs?: { gross: Point[]; net: Point[]; by_year: Table; avg_per_trade: number };
  split?: Table;
};

export type TradesPayload = {
  trades: Table;
  dimensions: Record<string, Table>;
  streaks: {
    lengths: number[];
    win: number[];
    loss: number[];
    worst_loss_streak_pnl: number | null;
  } | null;
};

export type Candle = { t: number; o: number; h: number; l: number; c: number; v?: number };

export type TradeBars = {
  candles: Candle[];
  intraday: boolean;
  entry?: { t: number; px: number };
  exit?: { t: number; px: number };
  stop?: number | null;
  win?: boolean;
  exit_reason?: string;
};

export type HoldingsPayload = {
  name: string;
  strategy: string;
  how_it_works: string;
  caveats: string[];
  calendar: string[];
  date: string;
  equity_t: number;
  since_start: number;
  drawdown_t: number;
  cash_weight: number;
  positions: Table;
  distinct: number;
  rebalances: string[];
  ranking: {
    formation: string;
    traded_on: string | null;
    changes: { bought: string[]; sold: string[]; kept: string[] };
    table: Table;
  } | null;
};

export type Timeline = {
  equity: Point[];
  benchmark: Point[];
  periods: { ticker: string; start: string; end: string }[];
};

export type Health = { name: string; status: "ok" | "warn" | "bad"; detail: string; last: string | null };

export type Ledger = {
  name: string;
  kind: string;
  error?: string;
  start: string | null;
  end: string | null;
  start_equity: number | null;
  equity_now: number | null;
  return: number | null;
  max_dd: number | null;
  days: number;
  cash: number | null;
  equity: Point[];
  benchmark: Point[];
  positions: { symbol: string; shares: number; unit?: "shares" | "contracts"; price: number | null; value: number | null; weight: number | null }[];
  pending: { symbol: string; quantity: number; ref_price: number | null; asof: string }[];
  fills: Table | null;
  account?: string | null; // Alpaca paper account behind the ledger
  ideas?: Table | null; // AI competition follower: every journal idea and what happened to it
  commissions: { actual: number; modeled: number; orders: number } | null;
};

export type LivePayload = {
  ledgers: Ledger[];
  health: Health[];
  observations: {
    days: { date: string; kinds: Record<string, number> }[];
    last_connection: Record<string, unknown> | null;
  };
  kill_switch: boolean;
};

export type OrbMeta = { widths: { label: string; name: string }[]; top_n: number[]; rules: string };
export type OrbDays = { dates: string[]; traded: { date: string; R: number }[] };
export type OrbDay = {
  date: string;
  candidates: Table | null;
  summary: {
    candidates: number;
    top: number;
    broke_out: number;
    day_R: number;
    day_net: number;
    capital: number;
  } | null;
};
export type OrbChart = {
  ticker: string;
  rank: number;
  relvol: number;
  side: number;
  taken: boolean;
  candles: Candle[];
  or_end: number;
  path: {
    or_high: number;
    or_low: number;
    level: number;
    triggered: boolean;
    entry_time?: number;
    entry_px?: number;
    stop_px?: number;
    exit_time?: number;
    exit_px?: number;
    exit_reason?: string;
    same_minute_stop?: boolean;
  } | null;
  sizing: {
    shares: number;
    "position $": number;
    "gross $": number;
    "costs $": number;
    "net $": number;
    "risk $": number;
    R: number;
    capital: number;
  } | null;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, String(detail));
  }
  return res.json() as Promise<T>;
}

const q = (params: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
  return s.toString();
};

export const useStudies = () =>
  useQuery({
    queryKey: ["studies"],
    queryFn: () => get<{ statuses: Status[]; studies: StudySummary[]; problems: string[] }>("/api/studies"),
  });
export const useStudy = (slug: string) =>
  useQuery({ queryKey: ["study", slug], queryFn: () => get<Study>(`/api/studies/${slug}`) });
export const useDoc = (ref: string | null) =>
  useQuery({
    queryKey: ["doc", ref],
    queryFn: () => get<Doc>(`/api/doc?${q({ ref })}`),
    enabled: !!ref,
  });
export const usePapers = () => useQuery({ queryKey: ["papers"], queryFn: () => get<Table>("/api/papers") });
export const useFileTable = (ref: string | null) =>
  useQuery({
    queryKey: ["table", ref],
    queryFn: () => get<Table>(`/api/files/table?${q({ ref })}`),
    enabled: !!ref,
  });
export const useFileEquity = (ref: string | null) =>
  useQuery({
    queryKey: ["equity", ref],
    queryFn: () => get<{ series: { name: string; points: Point[] }[]; total: number }>(`/api/files/equity?${q({ ref })}`),
    enabled: !!ref,
    retry: false,
  });
export const rawUrl = (ref: string) => `/api/files/raw?${q({ ref })}`;

export const useRuns = () =>
  useQuery({ queryKey: ["runs"], queryFn: () => get<{ runs: RunRow[] }>("/api/backtests") });
export const useRun = (id: string) =>
  useQuery({ queryKey: ["run", id], queryFn: () => get<RunDetail>(`/api/backtests/${encodeURIComponent(id)}`) });
export const useTrades = (id: string, enabled = true) =>
  useQuery({
    queryKey: ["trades", id],
    queryFn: () => get<TradesPayload>(`/api/backtests/${encodeURIComponent(id)}/trades`),
    enabled,
  });
export const useTradeBars = (id: string, i: number | null) =>
  useQuery({
    queryKey: ["tradebars", id, i],
    queryFn: () => get<TradeBars>(`/api/backtests/${encodeURIComponent(id)}/trades/${i}/bars`),
    enabled: i !== null,
  });
export const useCompare = (ids: string[]) =>
  useQuery({
    queryKey: ["compare", ids],
    queryFn: () =>
      get<{ runs: { run_id: string; name: string; growth: Point[]; stats: Stats }[] }>(
        `/api/backtests/compare?${q({ ids: ids.join(",") })}`,
      ),
    enabled: ids.length > 0,
  });
export const useHoldings = (id: string, date: string | null, enabled = true) =>
  useQuery({
    queryKey: ["holdings", id, date],
    queryFn: () => get<HoldingsPayload>(`/api/backtests/${encodeURIComponent(id)}/holdings?${q({ date })}`),
    enabled,
    placeholderData: (prev) => prev,
  });
export const useTimeline = (id: string, enabled = true) =>
  useQuery({
    queryKey: ["timeline", id],
    queryFn: () => get<Timeline>(`/api/backtests/${encodeURIComponent(id)}/holdings/timeline`),
    enabled,
  });

export const useLive = () =>
  useQuery({ queryKey: ["live"], queryFn: () => get<LivePayload>("/api/live"), refetchInterval: 60_000 });

export type HealthCheck = { health: Health[]; checked_at: string };
/** Runs every check now, with a live read-only IB Gateway connection (takes a few seconds). */
export const runHealthCheck = () => get<HealthCheck>("/api/live/check");

export const useOrbMeta = () => useQuery({ queryKey: ["orbmeta"], queryFn: () => get<OrbMeta>("/api/orb/meta") });
export const useOrbDays = (width: string | undefined, topN: number) =>
  useQuery({
    queryKey: ["orbdays", width, topN],
    queryFn: () => get<OrbDays>(`/api/orb/days?${q({ width, top_n: topN })}`),
    enabled: !!width,
  });
export const useOrbDay = (width: string | undefined, date: string | null, topN: number, slip: number) =>
  useQuery({
    queryKey: ["orbday", width, date, topN, slip],
    queryFn: () => get<OrbDay>(`/api/orb/day?${q({ width, date, top_n: topN, slip })}`),
    enabled: !!width && !!date,
    placeholderData: (prev) => prev,
  });
export const useOrbChart = (
  width: string | undefined,
  date: string | null,
  ticker: string | null,
  topN: number,
  slip: number,
) =>
  useQuery({
    queryKey: ["orbchart", width, date, ticker, topN, slip],
    queryFn: () => get<OrbChart>(`/api/orb/chart?${q({ width, date, ticker, top_n: topN, slip })}`),
    enabled: !!width && !!date && !!ticker,
  });

/** Rows of a Table as objects keyed by column. */
export function records<T = Record<string, unknown>>(t: Table | null | undefined): T[] {
  if (!t) return [];
  return t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i]])) as T);
}

export type JournalForecastStat = {
  horizon: number;
  group: string;
  n: number;
  hit_rate: number | null;
  always_up_hit_rate: number | null;
  mean_edge_pct: number | null;
  t_nonoverlap: number | null;
  n_nonoverlap: number;
};
export type JournalSummary = {
  updated: string;
  forecasts: JournalForecastStat[];
  by_confidence: { confidence: number; n: number; hit_rate: number }[];
  ideas: {
    opened: number;
    open: number;
    closed: number;
    pnl: number;
    win_rate: number | null;
    paired: number;
    pnl_paired: number;
    mirror_pnl_paired: number;
    t_vs_mirror: number | null;
  };
};
export type JournalDayRow = {
  date: string;
  complete: boolean;
  regime?: "risk_on" | "neutral" | "risk_off";
  bias?: string;
  thesis?: string;
  invalidation?: string;
  debate_winner?: "bull" | "bear" | "split";
  opened?: number;
  proposed?: number;
  problems?: string[];
};
export type JournalPayload = {
  exists: boolean;
  summary: JournalSummary | null;
  days: JournalDayRow[];
  positions: Table;
  forecasts: Table | null;
  equity: Point[];
};
export type JournalResolution = {
  n: number;
  idea: Record<string, unknown> & { underlying: string; structure: string; thesis: string; invalidation: string; confidence: number };
  status: "opened" | "rejected";
  reason: string;
  id: string | null;
  mirror?: string;
};
export type JournalDay = {
  date: string;
  record: {
    decided_at: string;
    prompt_sha: string;
    models: Record<string, string>;
    decision: {
      regime: string;
      bias: string;
      thesis: string;
      invalidation: string;
      debate_winner: string;
      forecasts: { ticker: string; horizon_days: number; direction: string; benchmark: string; confidence: number }[];
      close_ids: string[];
    };
    problems: string[];
    resolution: JournalResolution[];
  } | null;
  packet: string | null;
  reports: Record<string, string>;
  meta: Record<string, { model: string; tools: string[]; started: string; finished: string; cost_usd: number | null; turns: number | null }>;
};

export const useJournal = () => useQuery({ queryKey: ["journal"], queryFn: () => get<JournalPayload>("/api/journal") });
export const useJournalDay = (day: string | null) =>
  useQuery({ queryKey: ["journalday", day], queryFn: () => get<JournalDay>(`/api/journal/${day}`), enabled: !!day });
