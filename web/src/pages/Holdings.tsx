import clsx from "clsx";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Bars, TimeChart } from "../components/charts";
import { Button, Card, CardTitle, DataTable, ErrorState, Kpi, Loading } from "../components/ui";
import { records, useHoldings, useTimeline, type Timeline } from "../lib/api";
import { compact, money, pct, tone } from "../lib/format";
import { SERIES } from "../lib/theme";

function Gantt({ data, date }: { data: Timeline; date: string }) {
  const tickers = useMemo(() => {
    const first = new Map<string, string>();
    data.periods.forEach((p) => (!first.has(p.ticker) || p.start < first.get(p.ticker)!) && first.set(p.ticker, p.start));
    return [...first.entries()].sort((a, b) => (a[1] < b[1] ? -1 : 1)).map(([t]) => t);
  }, [data]);
  if (!data.periods.length) return null;
  const t0 = Date.parse(data.equity[0] ? new Date(data.equity[0].t * 1000).toISOString() : data.periods[0].start);
  const t1 = Date.parse(new Date((data.equity[data.equity.length - 1]?.t ?? 0) * 1000).toISOString());
  const x = (d: string) => ((Date.parse(d) - t0) / (t1 - t0 || 1)) * 100;
  const row = 14;
  return (
    <div className="max-h-[520px] overflow-auto">
      <div className="relative" style={{ height: tickers.length * row + 8 }}>
        <div className="absolute inset-y-0 w-px bg-accent" style={{ left: `calc(4.5rem + (100% - 4.5rem) * ${x(date) / 100})` }} />
        {tickers.map((tk, i) => (
          <div key={tk} className="absolute inset-x-0 flex items-center" style={{ top: i * row, height: row }}>
            <div className="num w-[4.5rem] shrink-0 truncate pr-2 text-right text-[10.5px] text-muted">{tk}</div>
            <div className="relative h-full flex-1">
              {data.periods
                .filter((p) => p.ticker === tk)
                .map((p, j) => (
                  <div
                    key={j}
                    title={`${tk}: ${p.start} → ${p.end}`}
                    className="absolute top-[3px] h-[8px] rounded-sm"
                    style={{ left: `${x(p.start)}%`, width: `max(2px, ${x(p.end) - x(p.start)}%)`, background: SERIES[i % SERIES.length], opacity: 0.85 }}
                  />
                ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function HoldingsTab({ runId }: { runId: string }) {
  const [date, setDate] = useState<string | null>(null);
  const [idx, setIdx] = useState<number | null>(null);
  const q = useHoldings(runId, date);
  const tl = useTimeline(runId);
  const cal = q.data?.calendar ?? [];
  useEffect(() => {
    if (idx === null || !cal.length) return;
    const h = setTimeout(() => setDate(cal[idx]), 120);
    return () => clearTimeout(h);
  }, [idx, cal]);
  if (q.isLoading && !q.data) return <Loading label="Loading holdings" />;
  if (q.error) return <ErrorState error={q.error} />;
  const h = q.data!;
  const i = idx ?? cal.indexOf(h.date);
  const jump = (dir: -1 | 1) => {
    const target = dir < 0 ? [...h.rebalances].reverse().find((d) => d < h.date) : h.rebalances.find((d) => d > h.date);
    if (target) {
      setIdx(cal.indexOf(target));
      setDate(target);
    }
  };
  const pos = records(h.positions);
  const idxCol = h.positions.columns[0];
  return (
    <div className="space-y-4">
      {h.how_it_works && (
        <details className="rounded-xl border border-line bg-panel px-4 py-3 text-[13px] text-muted">
          <summary className="cursor-pointer font-medium text-fg">How this strategy works</summary>
          <p className="mt-2 whitespace-pre-line leading-relaxed">{h.how_it_works}</p>
        </details>
      )}
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => jump(-1)} disabled={!h.rebalances.length} title="Previous rebalance">
            <ChevronLeft className="size-3.5" /> rebalance
          </Button>
          <input
            type="range"
            min={0}
            max={Math.max(0, cal.length - 1)}
            value={Math.max(0, i)}
            onChange={(e) => setIdx(Number(e.target.value))}
            className="min-w-40 flex-1 accent-[var(--accent)]"
          />
          <Button onClick={() => jump(1)} disabled={!h.rebalances.length} title="Next rebalance">
            rebalance <ChevronRight className="size-3.5" />
          </Button>
          <span className="num w-24 text-right text-[13px] font-semibold text-fg">{idx !== null ? cal[idx] : h.date}</span>
        </div>
        <p className="mt-2 text-xs text-faint">Positions at that day's close. {h.distinct} different stocks held over the run.</p>
      </Card>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Kpi label="Day" value={h.date} />
        <Kpi label="Equity" value={money(h.equity_t)} sub={<span className={tone(h.since_start)}>{pct(h.since_start, 1, true)} since start</span>} />
        <Kpi label="Below high" value={pct(h.drawdown_t)} tone={h.drawdown_t < 0 ? "text-neg" : undefined} />
        <Kpi label="Positions" value={pos.length} />
        <Kpi label="Cash" value={pct(h.cash_weight)} hint="Negative = borrowed: the simulator allows slightly negative cash and charges no margin interest." />
      </div>
      <div className="grid gap-4 lg:grid-cols-[2fr_3fr]">
        <Card>
          <CardTitle>Weights</CardTitle>
          <Bars
            format={(v) => pct(v)}
            rows={[...pos.map((p) => ({ label: String(p[idxCol]), value: Number(p.weight) })), { label: "cash", value: h.cash_weight }]}
          />
        </Card>
        <Card className="min-w-0">
          <CardTitle sub="Split-adjusted, dividends excluded.">Positions at the close</CardTitle>
          <DataTable
            data={h.positions}
            dense
            maxHeight={420}
            columns={h.positions.columns.map((c) => ({
              key: c,
              label: c === idxCol ? "ticker" : c,
              render:
                c === "weight" || c === "momentum" || c === "move since bought"
                  ? (v: unknown) => <span className={clsx("num", c !== "weight" && tone(v))}>{pct(v)}</span>
                  : c === "value" || c === "price"
                    ? (v: unknown) => <span className="num">{money(v)}</span>
                    : c === "held since"
                      ? (v: unknown) => <span className="num">{String(v ?? "").slice(0, 10)}</span>
                      : undefined,
            }))}
          />
        </Card>
      </div>
      {h.ranking && (
        <Card>
          <CardTitle sub={`Traded at the ${h.ranking.traded_on ?? "?"} open`}>Ranking at the {h.ranking.formation} close</CardTitle>
          <div className="mb-4 grid gap-3 text-[13px] sm:grid-cols-3">
            {(["bought", "sold", "kept"] as const).map((k) => (
              <div key={k} className="rounded-lg border border-line bg-panel-2 px-3 py-2">
                <div className={clsx("mb-1 text-[11px] font-semibold uppercase tracking-wider", k === "bought" ? "text-pos" : k === "sold" ? "text-neg" : "text-faint")}>{k}</div>
                <div className="num text-fg">{h.ranking!.changes[k].join(", ") || "–"}</div>
              </div>
            ))}
          </div>
          <DataTable
            data={h.ranking.table}
            dense
            maxHeight={420}
            rowClass={(r) => (r.selected ? "bg-accent-soft/60" : undefined)}
            columns={h.ranking.table.columns.map((c) => ({
              key: c,
              render: c === "momentum" ? (v: unknown) => <span className={clsx("num", tone(v))}>{pct(v)}</span> : c === "market_cap" ? (v: unknown) => <span className="num">{compact(v)}</span> : undefined,
            }))}
          />
        </Card>
      )}
      {tl.data && (
        <Card>
          <TimeChart
            title="Equity"
            height={240}
            lines={[{ name: "strategy", points: tl.data.equity }, ...(tl.data.benchmark.length ? [{ name: "benchmark", points: tl.data.benchmark }] : [])]}
          />
          <div className="mt-5">
            <CardTitle sub="Each bar is a continuous holding; the blue line is the selected day.">Holding periods</CardTitle>
            <Gantt data={tl.data} date={h.date} />
          </div>
        </Card>
      )}
    </div>
  );
}
