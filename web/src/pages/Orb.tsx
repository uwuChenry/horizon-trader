import clsx from "clsx";
import { AlertTriangle, Dices, Trophy, TrendingDown, Clock } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CandleChart, type Mark, type PriceLine } from "../components/charts";
import { Markdown } from "../components/Markdown";
import { Button, Callout, Card, CardTitle, DataTable, Empty, ErrorState, Kpi, Loading, PageHeader, Segmented, Select } from "../components/ui";
import { records, useOrbChart, useOrbDay, useOrbDays, useOrbMeta } from "../lib/api";
import { fixed, money, nyTime, tone } from "../lib/format";
import { tokens } from "../lib/theme";

/** One bar per traded day, coloured by the day's gross R, as a clickable strip. */
function DayStrip({ traded, value, onPick }: { traded: { date: string; R: number }[]; value: string | null; onPick: (d: string) => void }) {
  // scale to the 98th percentile so a few +10R days don't flatten the rest
  const sorted = traded.map((d) => Math.abs(d.R)).sort((a, b) => a - b);
  const max = Math.max(1, sorted[Math.floor(sorted.length * 0.98)] ?? 1);
  const W = traded.length;
  if (!W) return null;
  return (
    <div>
      <svg viewBox={`0 0 ${W} 40`} preserveAspectRatio="none" className="h-12 w-full cursor-pointer" onClick={(e) => {
        const r = (e.target as SVGElement).closest("svg")!.getBoundingClientRect();
        const i = Math.min(W - 1, Math.max(0, Math.floor(((e.clientX - r.left) / r.width) * W)));
        onPick(traded[i].date);
      }}>
        <line x1={0} x2={W} y1={20} y2={20} stroke="var(--border-strong)" strokeWidth={0.3} vectorEffect="non-scaling-stroke" />
        {traded.map((d, i) => {
          const h = (Math.min(Math.abs(d.R), max) / max) * 19;
          return <rect key={d.date} x={i} width={0.9} y={d.R >= 0 ? 20 - h : 20} height={Math.max(h, 0.4)} fill={d.R >= 0 ? "var(--pos)" : "var(--neg)"} opacity={d.date === value ? 1 : 0.7} />;
        })}
        {value && traded.findIndex((d) => d.date === value) >= 0 && (
          <rect x={traded.findIndex((d) => d.date === value) - 0.5} width={2} y={0} height={40} fill="var(--accent)" opacity={0.9} />
        )}
      </svg>
      <div className="num mt-1 flex justify-between text-[10.5px] text-faint">
        <span>{traded[0].date}</span>
        <span>gross R per traded day · click to jump</span>
        <span>{traded[W - 1].date}</span>
      </div>
    </div>
  );
}

export function OrbPage() {
  const meta = useOrbMeta();
  const [params, setParams] = useSearchParams();
  const width = params.get("width") ?? meta.data?.widths[0]?.name;
  const topN = Number(params.get("top") ?? 1);
  const slip = Number(params.get("slip") ?? 0);
  const days = useOrbDays(width, topN);
  const date = params.get("date") ?? days.data?.traded[days.data.traded.length - 1]?.date ?? null;
  const day = useOrbDay(width, date, topN, slip);
  const cands = useMemo(() => records(day.data?.candidates), [day.data]);
  const [ticker, setTicker] = useState<string | null>(null);
  useEffect(() => setTicker(null), [date, width]);
  const pick = ticker ?? (cands[0]?.ticker as string | undefined) ?? null;
  const chart = useOrbChart(width, date, pick, topN, slip);
  const set = (k: string, v: string | number | null) => {
    const p = new URLSearchParams(params);
    if (v === null || v === "") p.delete(k);
    else p.set(k, String(v));
    setParams(p, { replace: true });
  };
  const k = tokens();

  const jump = (how: "latest" | "best" | "worst" | "random") => {
    const t = days.data?.traded ?? [];
    if (!t.length) return;
    const d =
      how === "latest" ? t[t.length - 1] : how === "best" ? t.reduce((a, b) => (b.R > a.R ? b : a)) : how === "worst" ? t.reduce((a, b) => (b.R < a.R ? b : a)) : t[Math.floor(Math.random() * t.length)];
    set("date", d.date);
  };

  const { lines, marks } = useMemo(() => {
    const p = chart.data?.path;
    if (!p) return { lines: [] as PriceLine[], marks: [] as Mark[] };
    const long = (chart.data?.side ?? 1) > 0;
    const lines: PriceLine[] = [
      { price: p.or_high, color: k.accent, title: "OR high" },
      { price: p.or_low, color: k.accent, title: "OR low" },
    ];
    const marks: Mark[] = [];
    if (p.triggered && p.stop_px !== undefined && p.entry_time && p.exit_time) {
      lines.push({ price: p.stop_px, color: k.neg, title: "stop", dashed: true });
      marks.push({ t: p.entry_time, text: `${long ? "long" : "short"} ${fixed(p.entry_px)}`, color: k.accent, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown" });
      const win = (chart.data?.sizing?.R ?? 0) > 0;
      marks.push({ t: p.exit_time, text: `exit ${fixed(p.exit_px)}`, color: win ? k.pos : k.neg, position: long ? "aboveBar" : "belowBar", shape: "circle" });
    }
    return { lines, marks };
  }, [chart.data, k.accent, k.neg, k.pos]);

  if (meta.isLoading) return <Loading />;
  if (meta.error) return <ErrorState error={meta.error} />;
  if (!meta.data?.widths.length)
    return <Empty>No ORB trade table yet. Build it with uv run python -m horizon_trader.intraday.orb</Empty>;
  const s = day.data?.summary;
  const c = chart.data;

  return (
    <>
      <PageHeader
        eyebrow="Opening-range breakout on Stocks in Play · cached backtest trades"
        title={date ? new Date(date + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long", year: "numeric" }) : "ORB day"}
        right={
          <>
            <Button onClick={() => jump("latest")}>
              <Clock className="size-3.5" /> Latest
            </Button>
            <Button onClick={() => jump("best")}>
              <Trophy className="size-3.5" /> Best
            </Button>
            <Button onClick={() => jump("worst")}>
              <TrendingDown className="size-3.5" /> Worst
            </Button>
            <Button onClick={() => jump("random")}>
              <Dices className="size-3.5" /> Random
            </Button>
          </>
        }
      />
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <label className="flex flex-col gap-1 text-xs text-muted">
            Stop width
            <Select value={width ?? ""} onChange={(v) => set("width", v)} options={meta.data.widths.map((w) => ({ value: w.name, label: w.label }))} />
          </label>
          <div className="flex flex-col gap-1 text-xs text-muted">
            Stocks traded per day
            <Segmented value={topN} onChange={(v) => set("top", v === 1 ? null : v)} options={meta.data.top_n.map((n) => ({ value: n, label: `top ${n}` }))} />
          </div>
          <label className="flex flex-col gap-1 text-xs text-muted" title="Measured on 1-second bars: ~0.045 for a stop-market entry">
            Slippage per stop fill ($/sh)
            <input
              type="number"
              step={0.005}
              min={0}
              max={0.5}
              value={slip}
              onChange={(e) => set("slip", Number(e.target.value) || null)}
              className="num h-8 w-28 rounded-lg border border-line bg-panel px-2.5 text-[13px] text-fg outline-none focus:border-accent"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted">
            Day
            <input
              type="date"
              value={date ?? ""}
              min={days.data?.dates[0]}
              max={days.data?.dates[days.data.dates.length - 1]}
              onChange={(e) => set("date", e.target.value)}
              className="num h-8 rounded-lg border border-line bg-panel px-2.5 text-[13px] text-fg outline-none focus:border-accent"
            />
          </label>
        </div>
        {days.data && (
          <div className="mt-4">
            <DayStrip traded={days.data.traded} value={date} onPick={(d) => set("date", d)} />
          </div>
        )}
      </Card>

      {day.isLoading && !day.data ? (
        <Loading />
      ) : day.error ? (
        <ErrorState error={day.error} />
      ) : !s ? (
        <Empty>No stock passed the filters on {date}. It may be a holiday or a missing data day.</Empty>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi label="Stocks in play" value={s.candidates} />
            <Kpi label={`Top ${topN} broke out`} value={`${s.broke_out} of ${s.top}`} />
            <Kpi label="Day result (gross)" value={`${fixed(s.day_R, 2, true)} R`} tone={tone(s.day_R)} />
            <Kpi label={`Day P&L on ${money(s.capital)}`} value={money(s.day_net, { sign: true, cents: true })} tone={tone(s.day_net)} sub="IBKR Tiered, net" />
          </div>

          <div className="grid gap-4 xl:grid-cols-[3fr_2fr]">
            <Card className="min-w-0">
              <CardTitle
                sub={c ? `#${c.rank} by relative volume (${fixed(c.relvol, 1)}x) · ${c.side > 0 ? "long" : "short"} setup${c.taken ? "" : " · not traded at this top N"}` : undefined}
                right={
                  <Select value={pick ?? ""} onChange={setTicker} options={cands.map((r) => ({ value: String(r.ticker), label: `#${r.rank} ${r.ticker}${r.taken ? "" : " (not traded)"}` }))} />
                }
              >
                {pick}
              </CardTitle>
              {chart.isLoading ? (
                <Loading label="Loading minute bars" />
              ) : chart.error ? (
                <ErrorState error={chart.error} />
              ) : c?.candles.length ? (
                <CandleChart candles={c.candles} lines={lines} marks={marks} volume height={460} />
              ) : (
                <Empty>No minute bars cached for this day.</Empty>
              )}
            </Card>
            <div className="space-y-4">
              {c?.path && !c.path.triggered && (
                <Callout>
                  The price never broke the opening-range {c.side > 0 ? "high" : "low"} ({fixed(c.path.level)}), so there was no trade.
                </Callout>
              )}
              {c?.sizing && c.path && (
                <Card>
                  <CardTitle>The trade</CardTitle>
                  <p className="text-[13.5px] leading-relaxed text-fg">
                    <b>
                      {c.side > 0 ? "Bought" : "Shorted"} {c.sizing.shares.toLocaleString()} shares at {fixed(c.path.entry_px)}
                    </b>{" "}
                    ({c.path.entry_time ? new Date(c.path.entry_time * 1000).toISOString().slice(11, 16) : ""}), {money(c.sizing["position $"])} of stock,
                    risking {money(c.sizing["risk $"])} (1% of {money(c.sizing.capital)}) to a stop at {fixed(c.path.stop_px)}.{" "}
                    <b>Exit {fixed(c.path.exit_px)}</b> at {c.path.exit_time ? new Date(c.path.exit_time * 1000).toISOString().slice(11, 16) : ""} by {c.path.exit_reason}.
                  </p>
                  <div className="mt-4 grid grid-cols-2 gap-3">
                    <Kpi label="R multiple" value={`${fixed(c.sizing.R, 2, true)}R`} tone={tone(c.sizing.R)} />
                    <Kpi label="Net P&L" value={money(c.sizing["net $"], { sign: true, cents: true })} tone={tone(c.sizing["net $"])} />
                    <Kpi label="Gross" value={money(c.sizing["gross $"], { sign: true, cents: true })} />
                    <Kpi label="IBKR Tiered costs" value={money(c.sizing["costs $"], { cents: true })} />
                  </div>
                </Card>
              )}
              {c?.path?.same_minute_stop && (
                <Callout tone="warn">
                  <div className="flex gap-2">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" />
                    The stop was touched inside the entry minute. Minute bars can't say whether that happened before or after the fill; treat this result as uncertain.
                  </div>
                </Callout>
              )}
            </div>
          </div>

          <Card>
            <CardTitle sub="Click a row to chart it">Stocks in play, by relative volume</CardTitle>
            <DataTable
              data={day.data!.candidates!}
              dense
              maxHeight={null}
              selected={cands.findIndex((r) => r.ticker === pick)}
              onRowClick={(_, r) => setTicker(String(r.ticker))}
              rowClass={(r) => (r.taken ? undefined : "opacity-60")}
              columns={[
                { key: "rank" },
                { key: "ticker", render: (v) => <span className="font-semibold">{String(v)}</span> },
                { key: "taken", label: "traded", render: (v) => (v ? <span className="text-accent">yes</span> : <span className="text-faint">no</span>) },
                { key: "relvol", label: "rel. volume", align: "right", render: (v) => <span className="num">{fixed(v, 1)}x</span> },
                { key: "direction", render: (v) => <span className={v === "long" ? "text-pos" : "text-neg"}>{String(v)}</span> },
                { key: "level", label: "OR level", align: "right", render: (v) => <span className="num">{fixed(v)}</span> },
                { key: "stop_px", label: "stop", align: "right", render: (v) => <span className="num">{fixed(v)}</span> },
                { key: "triggered", label: "broke out", render: (v) => (v ? "yes" : <span className="text-faint">no</span>) },
                { key: "entry_time", label: "entry", render: (v) => <span className="num">{v ? nyTime(v) : ""}</span> },
                { key: "exit_reason", label: "exit" },
                { key: "exit_px", label: "exit px", align: "right", render: (v) => <span className="num">{fixed(v)}</span> },
                { key: "R", align: "right", render: (v) => <span className={clsx("num font-medium", tone(v))}>{v === null ? "" : fixed(v, 2, true)}</span> },
              ]}
            />
          </Card>

          <details className="rounded-xl border border-line bg-panel px-5 py-4">
            <summary className="cursor-pointer text-[13px] font-semibold text-fg">How the strategy works (rules)</summary>
            <div className="mt-3">
              <Markdown text={meta.data.rules} base="research/orb_experiments/README.md" />
            </div>
          </details>
        </div>
      )}
    </>
  );
}
