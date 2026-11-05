import clsx from "clsx";
import { CircleCheck, CircleX, Scale, TrendingDown, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { TimeChart } from "../components/charts";
import { Markdown } from "../components/Markdown";
import { Callout, Card, CardTitle, DataTable, Empty, ErrorState, Kpi, Loading, PageHeader, Segmented, Select, Tabs } from "../components/ui";
import { useJournal, useJournalDay, type JournalDayRow, type JournalForecastStat, type JournalPayload } from "../lib/api";
import { fixed, money, pct, tone } from "../lib/format";

const BASE = "research/forecast_journal/README.md";

const REGIME: Record<string, { label: string; cls: string }> = {
  risk_on: { label: "Risk on", cls: "bg-pos-soft text-pos" },
  neutral: { label: "Neutral", cls: "bg-panel-2 text-muted" },
  risk_off: { label: "Risk off", cls: "bg-neg-soft text-neg" },
};

function RegimeBadge({ regime }: { regime?: string }) {
  const r = REGIME[regime ?? ""] ?? REGIME.neutral;
  return <span className={clsx("rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider", r.cls)}>{r.label}</span>;
}

function headline(stats: JournalForecastStat[] | undefined, h: number) {
  return stats?.find((f) => f.horizon === h && f.group.startsWith("SPY"));
}

function Scorecard({ data }: { data: JournalPayload }) {
  const s = data.summary;
  const f1 = headline(s?.forecasts, 1);
  const f5 = headline(s?.forecasts, 5);
  const f20 = headline(s?.forecasts, 20);
  const i = s?.ideas;
  const days = data.days.filter((d) => d.complete).length;
  const vsMirror = i && i.paired ? i.pnl_paired - i.mirror_pnl_paired : null;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-7">
      <Kpi label="Days logged" value={days} sub={data.days[0]?.date ? `latest ${data.days[0].date}` : undefined} />
      <Kpi
        label="Next-day calls hit"
        value={f1?.n ? pct(f1.hit_rate, 0) : "–"}
        sub={f1?.n ? `always-up ${pct(f1.always_up_hit_rate, 0)} · n=${f1.n}` : "scored after the next close"}
        tone={f1?.n && f1.hit_rate !== null && f1.always_up_hit_rate !== null ? tone(f1.hit_rate - f1.always_up_hit_rate) : undefined}
      />
      <Kpi
        label="5-day calls hit"
        value={f5?.n ? pct(f5.hit_rate, 0) : "–"}
        sub={f5?.n ? `always-up ${pct(f5.always_up_hit_rate, 0)} · n=${f5.n}` : "scored after 5 trading days"}
        tone={f5?.n && f5.hit_rate !== null && f5.always_up_hit_rate !== null ? tone(f5.hit_rate - f5.always_up_hit_rate) : undefined}
      />
      <Kpi
        label="20-day calls hit"
        value={f20?.n ? pct(f20.hit_rate, 0) : "–"}
        sub={f20?.n ? `always-up ${pct(f20.always_up_hit_rate, 0)} · n=${f20.n}` : "scored after 20 trading days"}
        tone={f20?.n && f20.hit_rate !== null && f20.always_up_hit_rate !== null ? tone(f20.hit_rate - f20.always_up_hit_rate) : undefined}
      />
      <Kpi label="Ideas P&L (closed)" value={i?.closed ? money(i.pnl, { sign: true }) : "–"} tone={tone(i?.pnl)} sub={i ? `${i.closed} closed · ${i.open} open` : undefined} />
      <Kpi label="Ideas vs mirrors" value={vsMirror === null ? "–" : money(vsMirror, { sign: true })} tone={tone(vsMirror)} sub={i?.paired ? `${i.paired} pairs · t ${fixed(i.t_vs_mirror)}` : "the opposite trade, same moment"} />
      <Kpi label="Win rate" value={i?.win_rate === null || !i ? "–" : pct(i.win_rate, 0)} />
    </div>
  );
}

const ROLE_LABEL: Record<string, string> = {
  bull: "Bull case",
  bear: "Bear case",
  bull_rebuttal: "Bull rebuttal",
  bear_rebuttal: "Bear rebuttal",
  market: "Market analyst",
  news: "News analyst",
  earnings: "Earnings analyst",
  packet: "Market packet",
};

function DayView({ day }: { day: string }) {
  const { data, isLoading, error } = useJournalDay(day);
  const [role, setRole] = useState("bear");
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorState error={error} />;
  const rec = data.record;
  const roles = [...Object.keys(ROLE_LABEL).filter((r) => r in data.reports), ...(data.packet ? ["packet"] : [])];
  const shown = roles.includes(role) ? role : roles[0];
  const text = shown === "packet" ? data.packet ?? "" : data.reports[shown] ?? "";
  const cost = Object.values(data.meta).reduce((a, m) => a + (m.cost_usd ?? 0), 0);
  if (!rec) return <Callout tone="warn">This day's run didn't finish: {Object.keys(data.reports).length} of 7 reports, no decision.</Callout>;
  const d = rec.decision;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Card>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <RegimeBadge regime={d.regime} />
            <span className="text-sm font-semibold text-fg">{d.bias}</span>
            <span className="ml-auto flex items-center gap-1 text-xs text-muted">
              <Scale className="size-3.5" /> debate: <b className="text-fg">{d.debate_winner}</b>
            </span>
          </div>
          <p className="text-[15px] leading-relaxed text-fg">{d.thesis}</p>
          <p className="mt-3 text-sm text-muted">
            <span className="font-medium text-fg">Invalidation: </span>
            {d.invalidation}
          </p>
          {rec.problems.length > 0 && (
            <div className="mt-3">
              <Callout tone="warn">{rec.problems.join("; ")}</Callout>
            </div>
          )}
          <div className="mt-4 text-[11px] text-faint">
            Decided {rec.decided_at.replace("T", " ")} · prompt {rec.prompt_sha} · {rec.models.trader}
            {cost > 0 && ` · $${cost.toFixed(2)} of usage`}
          </div>
        </Card>
        <Card>
          <CardTitle sub="Close today → close after N trading days">Forecasts</CardTitle>
          <div className="divide-y divide-line">
            {d.forecasts.map((f, k) => (
              <div key={k} className="flex items-center gap-3 py-2 text-[13px]">
                {f.direction === "up" ? <TrendingUp className="size-4 text-pos" /> : <TrendingDown className="size-4 text-neg" />}
                <span className="num w-14 font-semibold text-fg">{f.ticker}</span>
                <span className="text-muted">
                  {f.horizon_days}d {f.direction}
                  {f.benchmark && ` vs ${f.benchmark}`}
                </span>
                <span className="ml-auto flex gap-0.5" title={`confidence ${f.confidence} of 5`}>
                  {[1, 2, 3, 4, 5].map((c) => (
                    <span key={c} className={clsx("h-2.5 w-1.5 rounded-sm", c <= f.confidence ? "bg-accent" : "bg-panel-2")} />
                  ))}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card>
        <CardTitle sub="Specs from the trader, priced and risk-checked by code. Each opened idea gets a mirror (the opposite trade).">Ideas</CardTitle>
        {rec.resolution.length === 0 ? (
          <Empty>No new trade today.</Empty>
        ) : (
          <div className="divide-y divide-line">
            {rec.resolution.map((r) => (
              <div key={r.n} className="flex items-start gap-3 py-3">
                {r.status === "opened" ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-pos" /> : <CircleX className="mt-0.5 size-4 shrink-0 text-faint" />}
                <div className="min-w-0 text-[13px]">
                  <div className="font-medium text-fg">
                    {r.idea.structure.replaceAll("_", " ")} {r.idea.underlying}
                    <span className="num ml-2 text-xs font-normal text-muted">
                      {String(r.idea.days_to_expiry ?? "")}d expiry · {String(r.idea.otm_pct ?? "")}% OTM · hold {String(r.idea.horizon_days ?? "")}d · conf {r.idea.confidence}
                    </span>
                  </div>
                  <div className="mt-0.5 text-muted">{r.idea.thesis}</div>
                  <div className="mt-0.5 text-xs text-faint">
                    {r.status === "opened" ? `opened as ${r.id}; mirror ${r.mirror}` : `rejected: ${r.reason}`}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[13px] font-semibold tracking-tight text-fg">Reports and debate</h3>
          <div className="hidden sm:block">
            <Segmented size="sm" value={shown} onChange={setRole} options={roles.map((r) => ({ value: r, label: ROLE_LABEL[r] }))} />
          </div>
          <Select className="sm:hidden" value={shown} onChange={setRole} options={roles.map((r) => ({ value: r, label: ROLE_LABEL[r] }))} />
        </div>
        {data.meta[shown] && (
          <div className="mb-3 text-[11px] text-faint">
            {data.meta[shown].model}
            {data.meta[shown].tools?.length ? ` · tools: ${data.meta[shown].tools.join(", ")}` : " · no tools"}
            {data.meta[shown].turns ? ` · ${data.meta[shown].turns} turns` : ""}
          </div>
        )}
        <Markdown text={text} base={BASE} />
      </Card>
    </div>
  );
}

function History({ days, onPick }: { days: JournalDayRow[]; onPick: (d: string) => void }) {
  return (
    <Card pad={false}>
      <div className="divide-y divide-line">
        {days.map((d) => (
          <button key={d.date} onClick={() => onPick(d.date)} className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-panel-2 sm:px-5">
            <span className="num w-24 shrink-0 text-[13px] text-muted">{d.date}</span>
            {d.complete ? (
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <RegimeBadge regime={d.regime} />
                  <span className="text-[13px] font-medium text-fg">{d.bias}</span>
                  <span className="text-xs text-faint">
                    debate {d.debate_winner} · {d.opened}/{d.proposed} ideas opened
                  </span>
                </div>
                <p className="line-clamp-2 text-[13px] text-muted">{d.thesis}</p>
              </div>
            ) : (
              <span className="text-[13px] text-warn">incomplete run</span>
            )}
          </button>
        ))}
      </div>
    </Card>
  );
}

function ForecastTab({ data }: { data: JournalPayload }) {
  const s = data.summary;
  return (
    <div className="space-y-4">
      <Card>
        <CardTitle sub="Hit = the call's direction was right. Always-up = the hit rate of calling 'up' on the same forecasts. t uses every h-th forecast so windows don't overlap.">
          Scorecard
        </CardTitle>
        {s && s.forecasts.some((f) => f.n) ? (
          <DataTable
            dense
            maxHeight={null}
            data={{
              columns: ["horizon", "group", "n", "hit_rate", "always_up_hit_rate", "mean_edge_pct", "t_nonoverlap", "n_nonoverlap"],
              rows: s.forecasts.map((f) => [f.horizon, f.group, f.n, f.hit_rate, f.always_up_hit_rate, f.mean_edge_pct, f.t_nonoverlap, f.n_nonoverlap]),
              total: s.forecasts.length,
            }}
            columns={[
              { key: "horizon", label: "Horizon", render: (v) => `${v}d` },
              { key: "group", label: "Forecasts" },
              { key: "n", label: "Scored", align: "right" },
              { key: "hit_rate", label: "Hit", align: "right", render: (v) => pct(v, 0) },
              { key: "always_up_hit_rate", label: "Always-up", align: "right", render: (v) => pct(v, 0) },
              { key: "mean_edge_pct", label: "Mean edge", align: "right", render: (v) => (v === null ? "–" : `${fixed(v, 2, true)}%`) },
              { key: "t_nonoverlap", label: "t", align: "right", render: (v) => fixed(v) },
              { key: "n_nonoverlap", label: "n (t)", align: "right" },
            ]}
          />
        ) : (
          <Empty>Nothing scored yet: the first 5-day calls resolve a week after the first run.</Empty>
        )}
      </Card>
      {data.forecasts && (
        <Card>
          <CardTitle sub="Every forecast; outcome columns fill in once the horizon has passed">All forecasts</CardTitle>
          <DataTable
            dense
            data={data.forecasts}
            columns={[
              { key: "date", label: "Date" },
              { key: "ticker", label: "Ticker" },
              { key: "horizon_days", label: "Days", align: "right" },
              { key: "direction", label: "Call" },
              { key: "benchmark", label: "vs" },
              { key: "confidence", label: "Conf", align: "right" },
              { key: "exit_date", label: "Scored on" },
              { key: "ret", label: "Return", align: "right", render: (v) => pct(v, 2, true) },
              { key: "edge", label: "Edge", align: "right", render: (v) => <span className={tone(v)}>{pct(v, 2, true)}</span> },
              { key: "hit", label: "Hit", align: "right", render: (v) => (v === null ? "" : v ? "✓" : "✗") },
            ]}
          />
        </Card>
      )}
    </div>
  );
}

function BookTab({ data }: { data: JournalPayload }) {
  return (
    <div className="space-y-4">
      {data.equity.length > 1 && (
        <Card>
          <TimeChart title="Hypothetical book: $10k + ideas (mirrors excluded)" height={260} lines={[{ name: "journal", points: data.equity }]} />
        </Card>
      )}
      <Card>
        <CardTitle sub="Bought at the ask, sold at the bid, $0.65 per contract assumed. Mirrors are the control.">Positions</CardTitle>
        {data.positions.total ? (
          <DataTable
            dense
            data={data.positions}
            rowClass={(r) => (r.kind === "mirror" ? "opacity-60" : undefined)}
            columns={[
              { key: "id", label: "Id" },
              { key: "kind", label: "Kind" },
              { key: "underlying", label: "Und." },
              { key: "structure", label: "Structure", render: (v) => String(v).replaceAll("_", " ") },
              { key: "contracts", label: "Legs", className: "num text-xs" },
              { key: "qty", label: "Qty", align: "right" },
              { key: "entry_cost", label: "Cost", align: "right", render: (v) => money(v) },
              { key: "last_value", label: "Value", align: "right", render: (v) => money(v) },
              { key: "exit_planned", label: "Closes by" },
              { key: "status", label: "Status" },
              { key: "exit_reason", label: "Why" },
              { key: "pnl", label: "P&L", align: "right", render: (v) => <span className={tone(v)}>{money(v, { sign: true })}</span> },
            ]}
          />
        ) : (
          <Empty>No positions yet.</Empty>
        )}
      </Card>
    </div>
  );
}

type Tab = "day" | "forecasts" | "book" | "history";

export function JournalPage() {
  const { data, isLoading, error } = useJournal();
  const [tab, setTab] = useState<Tab>("day");
  const [day, setDay] = useState<string | null>(null);
  useEffect(() => {
    if (!day && data?.days.length) setDay(data.days[0].date);
  }, [data, day]);
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorState error={error} />;
  return (
    <div>
      <PageHeader
        eyebrow="Forward test · no orders"
        title="Forecast journal"
        sub={
          <>
            Each trading day at 15:00 ET, analysts (market, news, earnings) report, a bull and a bear argue, and a trader writes down forecasts and trade
            specs before the outcome is known. Code prices the trades from live option quotes and scores everything.{" "}
            <Link className="text-accent hover:underline" to="/research/forecast_journal">
              Protocol and pass/fail rules
            </Link>
          </>
        }
        right={
          data.days.length > 0 && tab === "day" ? (
            <Select value={day ?? ""} onChange={setDay} options={data.days.map((d) => ({ value: d.date, label: d.date }))} />
          ) : undefined
        }
      />
      {!data.days.length ? (
        <Card>
          <Empty>
            No journal yet. Run <code className="num">uv run python -m horizon_trader.agents.journal run</code> during market hours (15:00 ET is the schedule).
          </Empty>
        </Card>
      ) : (
        <div className="space-y-5">
          <Scorecard data={data} />
          <Tabs
            value={tab}
            onChange={setTab}
            tabs={[
              { value: "day", label: "Day" },
              { value: "forecasts", label: "Forecasts" },
              { value: "book", label: "Book" },
              { value: "history", label: "History" },
            ]}
          />
          {tab === "day" && day && <DayView day={day} />}
          {tab === "forecasts" && <ForecastTab data={data} />}
          {tab === "book" && <BookTab data={data} />}
          {tab === "history" && (
            <History
              days={data.days}
              onPick={(d) => {
                setDay(d);
                setTab("day");
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
