import clsx from "clsx";
import { AlertTriangle, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Bars, CandleChart, Histogram, MonthlyHeatmap, Scatter, TimeChart, ValueHistogram } from "../components/charts";
import {
  Callout,
  Card,
  CardTitle,
  DataTable,
  Empty,
  ErrorState,
  Kpi,
  KpiRow,
  Loading,
  Segmented,
  Select,
  StatList,
  Tabs,
} from "../components/ui";
import { records, useRun, useTradeBars, useTrades, type RunDetail, type Table } from "../lib/api";
import { fixed, isNum, money, nyTime, pct, stat, tone } from "../lib/format";
import { tokens } from "../lib/theme";
import { HoldingsTab } from "./Holdings";

type TabKey = "overview" | "performance" | "trades" | "costs" | "holdings" | "honesty";

function statRows(s: Record<string, number | null>): [string, string, string?][] {
  return Object.entries(s).map(([k, v]) => [k, stat(k, v), k.includes("P&L") || k === "CAGR" || k === "alpha/yr" ? tone(v) : undefined]);
}

function Overview({ run }: { run: RunDetail }) {
  const [log, setLog] = useState((run.stats["total return"] ?? 0) > 1);
  const lines = [
    { name: "strategy", points: run.equity },
    ...(run.benchmark.length ? [{ name: run.meta.benchmark ?? "benchmark", points: run.benchmark, width: 1.5 }] : []),
  ];
  const oos = run.meta.oos_start;
  return (
    <div className="space-y-4">
      <Card>
        <TimeChart
          title="Equity"
          lines={lines}
          log={log}
          height={380}
          markers={oos ? [{ t: Date.parse(oos) / 1000, text: "out-of-sample →" }] : undefined}
          right={<Segmented size="sm" value={log ? "log" : "lin"} onChange={(v) => setLog(v === "log")} options={[{ value: "lin", label: "Linear" }, { value: "log", label: "Log" }]} />}
        />
      </Card>
      <Card>
        <TimeChart title="Drawdown" fmt="pct" height={170} lines={[{ name: "drawdown", points: run.drawdown, kind: "area", color: tokens().neg }]} />
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>Portfolio</CardTitle>
          <StatList rows={statRows(run.stats)} />
        </Card>
        <Card>
          <CardTitle>Trades</CardTitle>
          {run.trades ? <StatList rows={statRows(run.trade_stats)} /> : <Empty>This run has no trades.</Empty>}
        </Card>
      </div>
    </div>
  );
}

function Performance({ run }: { run: RunDetail }) {
  const [win, setWin] = useState("126");
  return (
    <div className="space-y-4">
      <Card>
        <CardTitle sub="Each cell is that month's return; the last column compounds the year.">Monthly returns</CardTitle>
        <MonthlyHeatmap months={run.monthly.months} rows={run.monthly.rows} />
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <TimeChart
            title="Rolling Sharpe"
            fmt="num"
            height={240}
            zeroLine
            lines={[{ name: `${win}-day`, points: run.rolling_sharpe[win] ?? [] }]}
            right={<Segmented size="sm" value={win} onChange={setWin} options={["63", "126", "252"].map((w) => ({ value: w, label: `${w}d` }))} />}
          />
        </Card>
        <Card>
          <CardTitle sub="0.25% buckets">Daily returns</CardTitle>
          <Histogram edges={run.daily_hist.edges} counts={run.daily_hist.counts} height={220} unit="%" />
        </Card>
      </div>
      <Card>
        <CardTitle>Worst drawdowns</CardTitle>
        <DataTable
          data={run.drawdowns}
          maxHeight={null}
          columns={run.drawdowns.columns.map((c) => ({
            key: c,
            render: c === "depth" ? (v: unknown) => <span className="num text-neg">{pct(v)}</span> : undefined,
          }))}
        />
      </Card>
    </div>
  );
}

function IndexLine({ values, height = 220 }: { values: number[]; height?: number }) {
  if (values.length < 2) return null;
  const W = 600;
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const y = (v: number) => height - 18 - ((v - lo) / (hi - lo || 1)) * (height - 28);
  const step = Math.max(1, Math.floor(values.length / 1500));
  const d = values
    .filter((_, i) => i % step === 0 || i === values.length - 1)
    .map((v, i, a) => `${i ? "L" : "M"}${((i / (a.length - 1)) * W).toFixed(1)},${y(v).toFixed(1)}`)
    .join("");
  const last = values[values.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }}>
      <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke="var(--border-strong)" vectorEffect="non-scaling-stroke" />
      <path d={d} fill="none" stroke={last >= 0 ? "var(--pos)" : "var(--neg)"} strokeWidth={1.8} vectorEffect="non-scaling-stroke" />
      <text x={4} y={height - 4} fontSize={11} fill="var(--faint)">
        trade 1
      </text>
      <text x={W - 4} y={height - 4} fontSize={11} fill="var(--faint)" textAnchor="end">
        trade {values.length.toLocaleString()}
      </text>
    </svg>
  );
}

function TradeChart({ runId, index, trade }: { runId: string; index: number; trade: Record<string, unknown> }) {
  const q = useTradeBars(runId, index);
  const k = tokens();
  const marks = useMemo(() => {
    if (!q.data?.entry || !q.data.exit) return [];
    const long = trade["side label"] !== "short";
    const c = q.data.win ? k.pos : k.neg;
    return [
      { t: q.data.entry.t, text: `${long ? "buy" : "short"} ${fixed(q.data.entry.px)}`, color: k.accent, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown" },
      { t: q.data.exit.t, text: `exit ${fixed(q.data.exit.px)}`, color: c, position: long ? "aboveBar" : "belowBar", shape: long ? "arrowDown" : "arrowUp" },
    ] as const;
  }, [q.data, trade, k.accent, k.neg, k.pos]);
  if (q.isLoading) return <Loading label="Loading bars" />;
  if (q.error) return <ErrorState error={q.error} />;
  if (!q.data?.candles.length) return <Empty>No local price data for this trade.</Empty>;
  const lines = isNum(q.data.stop) ? [{ price: q.data.stop, color: k.neg, title: "stop", dashed: true }] : [];
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3 text-[13px]">
        <span className="font-semibold text-fg">{String(trade.symbol)}</span>
        <span className="text-muted">{String(trade.entry_time ?? "").slice(0, 10)}</span>
        <span className="text-muted">{String(trade["side label"])}</span>
        <span className={clsx("num font-semibold", tone(trade.pnl))}>{money(trade.pnl, { sign: true })}</span>
        {isNum(trade.R) && <span className={clsx("num", tone(trade.R))}>{fixed(trade.R, 2, true)}R</span>}
        <span className="text-faint">{q.data.exit_reason}</span>
      </div>
      <CandleChart candles={q.data.candles} intraday={q.data.intraday} lines={lines} marks={[...marks]} height={400} />
    </div>
  );
}

function Trades({ run }: { run: RunDetail }) {
  const q = useTrades(run.run_id);
  const [unit, setUnit] = useState<"$" | "R">("$");
  const [dim, setDim] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const trades = useMemo(() => records(q.data?.trades), [q.data]);
  if (q.isLoading) return <Loading label="Loading trades" />;
  if (q.error) return <ErrorState error={q.error} />;
  if (!trades.length) return <Empty>This run has no trades.</Empty>;
  const d = q.data!;
  const hasR = trades.some((t) => isNum(t.R));
  const u = hasR ? unit : "$";
  const vals = trades.map((t) => Number(u === "R" ? t.R : t.pnl));
  const cum = trades.reduce<number[]>((a, t) => (a.push((a[a.length - 1] ?? 0) + Number(t.pnl)), a), []);
  const dims = Object.keys(d.dimensions);
  const curDim = dim ?? dims[0];
  const bd = records(d.dimensions[curDim]);
  const key = Object.keys(bd[0] ?? {})[0];
  const col = u === "R" && bd.some((r) => "avg R" in r) ? "avg R" : "avg P&L";
  const hasMae = trades.some((t) => isNum(t.mae_R) && isNum(t.mfe_R));
  const ts = run.trade_stats;
  return (
    <div className="space-y-4">
      {hasR && (
        <Segmented value={unit} onChange={setUnit} options={[{ value: "$", label: "Dollars" }, { value: "R", label: "R multiples" }]} />
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle sub="Tails clipped to the 1st-99th percentile">P&amp;L per trade ({u})</CardTitle>
          <ValueHistogram values={vals} height={220} unit={u === "R" ? "R" : ""} />
        </Card>
        <Card>
          <CardTitle sub={`Total ${money(cum[cum.length - 1], { sign: true })} over ${trades.length.toLocaleString()} trades`}>Cumulative P&amp;L by trade</CardTitle>
          <IndexLine values={cum} />
        </Card>
      </div>
      {d.streaks && (
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <Card>
            <CardTitle>Streak lengths</CardTitle>
            <div className="grid grid-cols-2 gap-6">
              {(["win", "loss"] as const).map((kind) => (
                <div key={kind}>
                  <div className="mb-2 text-xs font-medium capitalize text-muted">{kind} streaks</div>
                  <Bars
                    format={(v) => v.toLocaleString()}
                    rows={d.streaks!.lengths
                      .map((len, i) => ({ label: `${len} in a row`, value: (kind === "win" ? d.streaks!.win[i] : d.streaks!.loss[i]) ?? 0, tone: kind === "win" ? ("pos" as const) : ("neg" as const) }))
                      .filter((r) => r.value > 0)}
                  />
                </div>
              ))}
            </div>
          </Card>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-1">
            <Kpi label="Longest win streak" value={stat("", ts["max win streak"])} />
            <Kpi label="Longest loss streak" value={stat("", ts["max loss streak"])} />
            <Kpi label="Worst losing streak" value={money(d.streaks.worst_loss_streak_pnl)} tone="text-neg" hint="Sum of P&L over the costliest run of consecutive losses" />
          </div>
        </div>
      )}
      {hasMae && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardTitle sub="Worst (MAE) and best (MFE) point before exit, in R">MAE vs MFE</CardTitle>
            <Scatter points={trades.map((t) => ({ x: Number(t.mae_R), y: Number(t.mfe_R), good: Number(t.pnl) > 0 }))} xLabel="MAE (R)" yLabel="MFE (R)" />
          </Card>
          <Card>
            <CardTitle sub="MFE minus the realised R">Profit given back before exit</CardTitle>
            <ValueHistogram values={trades.map((t) => Number(t.mfe_R) - Number(t.R))} height={240} unit="R" />
          </Card>
        </div>
      )}
      <Card>
        <CardTitle right={<Select value={curDim} onChange={setDim} options={dims.map((x) => ({ value: x, label: x }))} />}>Breakdown by {curDim}</CardTitle>
        <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
          <Bars
            format={(v) => (col === "avg R" ? fixed(v, 2, true) + "R" : money(v, { sign: true }))}
            rows={bd.map((r) => ({ label: String(r[key]), value: Number(r[col]) || 0, note: `${r.trades}` }))}
          />
          <DataTable
            data={d.dimensions[curDim]}
            maxHeight={320}
            dense
            columns={d.dimensions[curDim].columns.map((c) => ({ key: c, render: c === "win rate" ? (v: unknown) => pct(v, 0) : undefined }))}
          />
        </div>
      </Card>
      <Card>
        <CardTitle sub="Click a row to chart the trade">Trade list</CardTitle>
        {sel !== null && (
          <div className="mb-4">
            <TradeChart runId={run.run_id} index={sel} trade={trades[sel]} />
          </div>
        )}
        <DataTable
          data={d.trades}
          dense
          maxHeight={420}
          selected={sel}
          onRowClick={(i) => setSel(i)}
          columns={d.trades.columns
            .filter((c) => c !== "result")
            .map((c) => ({
              key: c,
              render:
                c === "pnl" || c === "gross"
                  ? (v: unknown) => <span className={clsx("num", tone(v))}>{money(v, { cents: true })}</span>
                  : c === "R"
                    ? (v: unknown) => <span className={clsx("num", tone(v))}>{fixed(v, 2, true)}</span>
                    : (c === "entry_time" || c === "exit_time") && run.meta.chart === "massive_minute"
                      ? (v: unknown) => <span className="num">{String(v).slice(0, 10)} {nyTime(v)}</span>
                      : undefined,
            }))}
        />
      </Card>
    </div>
  );
}

function Costs({ run }: { run: RunDetail }) {
  if (!run.costs) return <Empty>This run has no trades.</Empty>;
  const k = tokens();
  return (
    <div className="space-y-4">
      <Card>
        <TimeChart
          title="Cumulative P&L before vs after costs"
          height={340}
          lines={[
            { name: "before costs", points: run.costs.gross, color: k.accent },
            { name: "after costs", points: run.costs.net, color: k.warn },
          ]}
        />
      </Card>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Kpi label="Total costs" value={money(run.trade_stats.costs)} tone="text-neg" />
        <Kpi label="Costs / gross profit" value={pct(run.trade_stats["costs / gross profit"])} />
        <Kpi label="Avg cost per trade" value={money(run.costs.avg_per_trade, { cents: true })} />
      </div>
      <Card>
        <CardTitle sub={run.meta.costs_description ?? "Commissions and regulatory fees. Slippage is inside the fill prices, so it shows up in 'before costs' P&L."}>
          By year
        </CardTitle>
        <DataTable
          data={run.costs.by_year}
          maxHeight={null}
          columns={run.costs.by_year.columns.map((c) => ({
            key: c,
            render: c === "year" ? undefined : (v: unknown) => <span className={clsx("num", c !== "costs" && tone(v))}>{money(v)}</span>,
          }))}
        />
      </Card>
    </div>
  );
}

function SplitTable({ split }: { split: Table }) {
  const keep = ["CAGR", "Sharpe", "max DD", "trades", "win rate", "profit factor", "expectancy $", "expectancy R", "costs / gross profit"];
  const rows = split.rows.filter((r) => keep.includes(String(r[0])));
  return (
    <DataTable
      data={{ ...split, rows, total: rows.length }}
      maxHeight={null}
      columns={split.columns.map((c, i) => ({
        key: c,
        label: i === 0 ? "metric" : c,
        render: i === 0 ? undefined : (v: unknown, r: Record<string, unknown>) => <span className="num">{stat(String(r[split.columns[0]]), v)}</span>,
      }))}
    />
  );
}

function Honesty({ run }: { run: RunDetail }) {
  const share = run.trade_stats["best 5% share of P&L"];
  return (
    <div className="space-y-4">
      <Card>
        <CardTitle>Caveats</CardTitle>
        {run.meta.caveats?.length ? (
          <ul className="list-disc space-y-1.5 pl-5 text-[13.5px] leading-relaxed text-fg">
            {run.meta.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">None recorded for this run.</p>
        )}
      </Card>
      {run.split && (
        <Card>
          <CardTitle sub="If the second column is much worse than the first, the result is probably fitted to the past.">
            In-sample vs out-of-sample (split {run.meta.oos_start})
          </CardTitle>
          <SplitTable split={run.split} />
        </Card>
      )}
      {isNum(share) && (
        <div className="max-w-xs">
          <Kpi label="P&L from the best 5% of trades" value={pct(share, 0)} hint="Above 100% means the other 95% of trades lost money in total." tone={share > 1 ? "text-warn" : undefined} />
        </div>
      )}
      <Card>
        <CardTitle>Run details</CardTitle>
        <p className="mb-3 text-[13px] text-muted">
          Commit <code className="num text-fg">{run.meta.git_commit ?? "?"}</code>
          {run.meta.git_dirty && <span className="ml-1 font-semibold text-warn">with uncommitted changes</span>} · created{" "}
          <span className="num">{run.meta.created?.slice(0, 16).replace("T", " ")}</span>
        </p>
        <pre className="num max-h-96 overflow-auto rounded-lg border border-line bg-panel-2 p-4 text-[12px] text-fg">{JSON.stringify(run.meta.params ?? {}, null, 2)}</pre>
      </Card>
    </div>
  );
}

export function BacktestPage() {
  const runId = useParams().runId!;
  const q = useRun(runId);
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as TabKey) ?? "overview";
  if (q.isLoading) return <Loading label="Loading run" />;
  if (q.error) return <ErrorState error={q.error} />;
  const run = q.data!;
  const s = run.stats;
  const ts = run.trade_stats;
  const caveats = run.meta.caveats ?? [];
  return (
    <>
      <nav className="mb-4 flex items-center gap-1 text-xs text-muted">
        <Link to="/backtests" className="hover:text-fg">
          Backtests
        </Link>
        <ChevronRight className="size-3 text-faint" />
        <span className="truncate text-fg">{run.meta.name ?? runId}</span>
      </nav>
      <div className="mb-5">
        <h1 className="text-xl font-semibold tracking-tight text-fg sm:text-2xl">{run.meta.name ?? runId}</h1>
        <p className="mt-1 text-sm text-muted">{run.meta.strategy}</p>
        <p className="num mt-1 text-xs text-faint">
          {run.meta.start?.slice(0, 10)} → {run.meta.end?.slice(0, 10)} · commit {run.meta.git_commit ?? "?"}
          {run.meta.git_dirty ? " (dirty)" : ""}
        </p>
      </div>
      <KpiRow>
        <Kpi label="Total P&L" value={money(s["total P&L"])} tone={tone(s["total P&L"])} />
        <Kpi label="CAGR" value={pct(s.CAGR)} tone={tone(s.CAGR)} />
        <Kpi label="Sharpe" value={fixed(s.Sharpe)} />
        <Kpi label="Max drawdown" value={pct(s["max DD"])} tone="text-neg" />
        <Kpi label="Profit factor" value={fixed(ts["profit factor"])} />
        <Kpi label="Win rate" value={pct(ts["win rate"], 0)} />
        <Kpi label="Trades" value={(run.trades ?? 0).toLocaleString()} />
        <Kpi label="Expectancy" value={isNum(ts["expectancy R"]) ? `${fixed(ts["expectancy R"], 2, true)}R` : money(ts["expectancy $"], { sign: true })} />
      </KpiRow>
      {!!caveats.length && (
        <div className="mt-4">
          <Callout tone="warn">
            <div className="flex gap-2">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" />
              <div>
                {caveats.slice(0, 2).join(" · ")}
                {caveats.length > 2 && (
                  <button className="ml-2 font-medium text-accent hover:underline" onClick={() => setParams({ tab: "honesty" }, { replace: true })}>
                    all {caveats.length} caveats
                  </button>
                )}
              </div>
            </div>
          </Callout>
        </div>
      )}
      <div className="mt-6">
        <Tabs
          value={tab}
          onChange={(v) => setParams(v === "overview" ? {} : { tab: v }, { replace: true })}
          tabs={[
            { value: "overview", label: "Overview" },
            { value: "performance", label: "Performance" },
            { value: "trades", label: "Trades", hidden: !run.trades },
            { value: "costs", label: "Costs", hidden: !run.trades },
            { value: "holdings", label: "Holdings", hidden: !run.holdings },
            { value: "honesty", label: "Honesty" },
          ]}
        />
      </div>
      {tab === "overview" && <Overview run={run} />}
      {tab === "performance" && <Performance run={run} />}
      {tab === "trades" && <Trades run={run} />}
      {tab === "costs" && <Costs run={run} />}
      {tab === "holdings" && <HoldingsTab runId={runId} />}
      {tab === "honesty" && <Honesty run={run} />}
    </>
  );
}
