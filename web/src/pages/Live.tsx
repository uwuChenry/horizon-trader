import clsx from "clsx";
import { useState } from "react";
import { CircleCheck, CircleAlert, CircleX, OctagonX, RefreshCw, Stethoscope } from "lucide-react";
import { TimeChart } from "../components/charts";
import { Bars } from "../components/charts";
import { Button, Callout, Card, CardTitle, DataTable, Empty, ErrorState, Kpi, Loading, PageHeader } from "../components/ui";
import { runHealthCheck, useLive, type Health, type HealthCheck, type Ledger } from "../lib/api";
import { fixed, money, pct, tone } from "../lib/format";
import { tokens } from "../lib/theme";

export function HealthList({ items }: { items: Health[] }) {
  return (
    <div className="divide-y divide-line">
      {items.map((h) => {
        const Icon = h.status === "ok" ? CircleCheck : h.status === "warn" ? CircleAlert : CircleX;
        return (
          <div key={h.name} className="flex items-start gap-3 py-2.5">
            <Icon className={clsx("mt-0.5 size-4 shrink-0", h.status === "ok" ? "text-pos" : h.status === "warn" ? "text-warn" : "text-neg")} />
            <div className="min-w-0">
              <div className="text-[13px] font-medium text-fg">{h.name}</div>
              <div className="text-xs text-muted">{h.detail}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function LedgerCard({ l }: { l: Ledger }) {
  if (l.error) return <ErrorState error={`${l.name}: ${l.error}`} />;
  const k = tokens();
  const spy = l.benchmark.length ? l.benchmark[l.benchmark.length - 1].v / l.benchmark[0].v - 1 : null;
  const c = l.commissions;
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-lg font-semibold tracking-tight text-fg">{l.name.replaceAll("_", " ")}</h2>
        <span className="rounded-full bg-panel-2 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">{l.kind}</span>
        {l.account && <span className="num text-xs text-muted">Alpaca {l.account}</span>}
        <span className="num text-xs text-faint">
          {l.start} → {l.end} · {l.days} days
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Equity" value={money(l.equity_now)} sub={`from ${money(l.start_equity)}`} />
        <Kpi label="Return" value={pct(l.return, 2, true)} tone={tone(l.return)} />
        <Kpi label="SPY same period" value={pct(spy, 2, true)} tone={tone(spy)} sub={spy !== null && l.return !== null ? `${pct(l.return - spy, 2, true)} vs SPY` : undefined} />
        <Kpi label="Max drawdown" value={pct(l.max_dd)} tone="text-neg" />
        <Kpi label="Cash" value={money(l.cash)} />
        <Kpi label="Commissions" value={money(c?.actual, { cents: true })} sub={c ? `${c.orders} orders · model ${money(c.modeled, { cents: true })}` : undefined} />
      </div>
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Card>
          <TimeChart
            title="Equity vs SPY (rescaled)"
            height={300}
            lines={[{ name: "ledger", points: l.equity }, ...(l.benchmark.length ? [{ name: "SPY", points: l.benchmark, color: k.faint, dashed: true }] : [])]}
          />
        </Card>
        <Card>
          <CardTitle sub="Shares from the ledger, marked at the last cached close">Positions</CardTitle>
          {l.positions.length ? (
            <Bars
              format={(v) => pct(v)}
              rows={l.positions.map((p) => ({
                label: p.symbol,
                value: p.weight ?? 0,
                note: p.unit === "contracts" ? `${fixed(p.shares, 0, true)} contracts` : `${fixed(p.shares, p.shares < 10 ? 3 : 1)} sh`,
              }))}
            />
          ) : (
            <Empty>Flat.</Empty>
          )}
          {!!l.pending.length && (
            <div className="mt-4 border-t border-line pt-3">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-faint">Pending for next open</div>
              {l.pending.map((p, i) => (
                <div key={i} className="flex justify-between py-0.5 text-[13px]">
                  <span className={clsx("font-medium", p.quantity >= 0 ? "text-pos" : "text-neg")}>
                    {p.quantity >= 0 ? "BUY" : "SELL"} {p.symbol}
                  </span>
                  <span className="num text-muted">
                    {fixed(Math.abs(p.quantity), 4)}
                    {p.ref_price != null && <> @ ~{fixed(p.ref_price)}</>} · {p.asof}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
      {l.ideas && (
        <Card>
          <CardTitle sub="Every forecast-journal idea: opened, skipped or missed, and why. Quote source ibkr = live, otherwise Alpaca's indicative feed">
            Journal ideas
          </CardTitle>
          <DataTable
            data={l.ideas}
            dense
            maxHeight={360}
            columns={["id", "underlying", "structure", "confidence", "status", "qty", "limit", "cost", "quote_source", "reason", "close_reason"].map((c) => ({
              key: c,
              render: c === "cost" ? (v: unknown) => <span className="num">{money(v)}</span> : undefined,
            }))}
          />
        </Card>
      )}
      {l.fills && (
        <Card>
          <CardTitle sub="Most recent first">Fills</CardTitle>
          <DataTable
            data={l.fills}
            dense
            maxHeight={360}
            columns={["time", "symbol", "quantity", "price", "open_price", "commission", "modeled_commission", "source"].map((c) => ({
              key: c,
              render:
                c === "quantity"
                  ? (v: unknown) => <span className={clsx("num", tone(v))}>{fixed(v, 4, true)}</span>
                  : c.includes("commission")
                    ? (v: unknown) => <span className="num">{money(v, { cents: true })}</span>
                    : undefined,
            }))}
          />
        </Card>
      )}
    </section>
  );
}

function HealthCard({ items }: { items: Health[] }) {
  const [live, setLive] = useState<HealthCheck | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      setLive(await runHealthCheck());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };
  const when = live ? new Date(live.checked_at).toLocaleTimeString() : null;
  return (
    <Card>
      <CardTitle
        sub={
          live
            ? `Live check at ${when}, including a read-only IB Gateway connection`
            : "Weekday jobs and connections from the files on disk; holidays are not excluded"
        }
        right={
          <Button onClick={run} disabled={running} title="Run every check now, with a live IB Gateway connection">
            <Stethoscope className={clsx("size-3.5", running && "animate-pulse")} /> {running ? "Checking..." : "Run live check"}
          </Button>
        }
      >
        Health
      </CardTitle>
      {error && <ErrorState error={error} />}
      <HealthList items={live ? live.health : items} />
    </Card>
  );
}

export function LivePage() {
  const q = useLive();
  return (
    <>
      <PageHeader
        title="Live & paper"
        sub="Forward-test ledgers under data/live, IBKR connection observations and whether the scheduled jobs ran. Read-only; refreshes every minute."
        right={
          <Button onClick={() => q.refetch()}>
            <RefreshCw className={clsx("size-3.5", q.isFetching && "animate-spin")} /> Refresh
          </Button>
        }
      />
      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorState error={q.error} />
      ) : (
        <div className="space-y-8">
          {q.data!.kill_switch && (
            <Callout tone="bad">
              <div className="flex items-center gap-2 font-semibold">
                <OctagonX className="size-4" /> Kill switch is ON (data/live/KILL). No orders will be placed until it is removed.
              </div>
            </Callout>
          )}
          <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
            <HealthCard items={q.data!.health} />
            <Card>
              <CardTitle sub="Read-only IB Gateway sessions, last 14 logged days">IBKR observations</CardTitle>
              <div className="space-y-1.5">
                {[...q.data!.observations.days].reverse().map((d) => {
                  const ok = (d.kinds.connected ?? 0) + (d.kinds.account ?? 0) > 0;
                  const failed = d.kinds.connection_failed ?? 0;
                  return (
                    <div key={d.date} className="flex items-center gap-3 text-xs">
                      <span className="num w-20 text-muted">{d.date}</span>
                      <span className={clsx("size-2 rounded-full", ok ? "bg-pos" : failed ? "bg-neg" : "bg-faint")} />
                      <span className="truncate text-faint">
                        {Object.entries(d.kinds)
                          .map(([k, n]) => `${k.replaceAll("_", " ")} ${n}`)
                          .join(" · ")}
                      </span>
                    </div>
                  );
                })}
                {!q.data!.observations.days.length && <Empty>No observations logged.</Empty>}
              </div>
            </Card>
          </div>
          {q.data!.ledgers.length ? q.data!.ledgers.map((l) => <LedgerCard key={l.name} l={l} />) : <Empty>No ledgers under data/live yet.</Empty>}
        </div>
      )}
    </>
  );
}
