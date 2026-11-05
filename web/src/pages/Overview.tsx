import clsx from "clsx";
import { ArrowRight } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Sparkline } from "../components/charts";
import { Card, CardTitle, ErrorState, Loading, PageHeader, STATUS } from "../components/ui";
import { useLive, useRuns, useStudies, type Status } from "../lib/api";
import { fixed, money, pct, tone } from "../lib/format";
import { HealthList } from "./Live";
import { StudyCard } from "./Research";

function More({ to, children }: { to: string; children: string }) {
  return (
    <Link to={to} className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline">
      {children} <ArrowRight className="size-3" />
    </Link>
  );
}

export function OverviewPage() {
  const live = useLive();
  const studies = useStudies();
  const runs = useRuns();
  const top = useMemo(() => (studies.data?.studies ?? []).filter((s) => !s.parent), [studies.data]);
  const active = top.filter((s) => ["core", "candidate", "running"].includes(s.status));
  const counts = useMemo(() => {
    const c: Partial<Record<Status, number>> = {};
    top.forEach((s) => (c[s.status] = (c[s.status] ?? 0) + 1));
    return c;
  }, [top]);
  const recent = useMemo(
    () => [...(runs.data?.runs ?? [])].sort((a, b) => (a.created < b.created ? 1 : -1)).slice(0, 6),
    [runs.data],
  );
  const warn = (live.data?.health ?? []).filter((h) => h.status !== "ok").length;
  const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });

  return (
    <>
      <PageHeader
        eyebrow={today}
        title="Overview"
        sub={
          live.data
            ? warn
              ? `${warn} check${warn > 1 ? "s" : ""} need${warn > 1 ? "" : "s"} attention.`
              : "All scheduled jobs and ledgers are up to date."
            : undefined
        }
      />
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Card>
          <CardTitle right={<More to="/live">Live page</More>}>Forward tests</CardTitle>
          {live.isLoading ? (
            <Loading />
          ) : live.error ? (
            <ErrorState error={live.error} />
          ) : (
            <div className="space-y-4">
              {live.data!.ledgers.map((l) => {
                const spy = l.benchmark.length ? l.benchmark[l.benchmark.length - 1].v / l.benchmark[0].v - 1 : null;
                return (
                  <Link key={l.name} to="/live" className="block rounded-lg border border-line bg-panel-2 p-4 transition-colors hover:border-line-strong">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <div className="text-[13px] font-semibold text-fg">{l.name.replaceAll("_", " ")}</div>
                      <div className="num text-[11px] text-faint">
                        since {l.start} · {l.days} days
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap items-end gap-x-6 gap-y-1">
                      <div className="num text-2xl font-semibold text-fg">{money(l.equity_now)}</div>
                      <div className={clsx("num text-sm font-medium", tone(l.return))}>{pct(l.return, 2, true)}</div>
                      {spy !== null && (
                        <div className="text-xs text-muted">
                          SPY <span className={clsx("num", tone(spy))}>{pct(spy, 2, true)}</span>
                        </div>
                      )}
                      <div className="text-xs text-muted">
                        max DD <span className="num text-neg">{pct(l.max_dd)}</span>
                      </div>
                    </div>
                    <Sparkline points={l.equity} height={44} className="mt-3" />
                  </Link>
                );
              })}
            </div>
          )}
        </Card>
        <Card>
          <CardTitle>Health</CardTitle>
          {live.data ? <HealthList items={live.data.health} /> : <Loading />}
        </Card>
      </div>

      <Card className="mt-4">
        <CardTitle right={<More to="/research">All research</More>} sub="Where each study stands, from its result.json">
          Research pipeline
        </CardTitle>
        {studies.isLoading ? (
          <Loading />
        ) : (
          <>
            <div className="mb-2 flex h-2.5 overflow-hidden rounded-full bg-panel-2">
              {(studies.data?.statuses ?? []).map((s) =>
                counts[s] ? <div key={s} className={STATUS[s].dot} style={{ width: `${(counts[s]! / top.length) * 100}%` }} title={`${STATUS[s].label}: ${counts[s]}`} /> : null,
              )}
            </div>
            <div className="mb-5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              {(studies.data?.statuses ?? []).map((s) =>
                counts[s] ? (
                  <Link key={s} to={`/research?status=${s}`} className="inline-flex items-center gap-1.5 hover:text-fg">
                    <span className={clsx("size-2 rounded-full", STATUS[s].dot)} />
                    {STATUS[s].label} <span className="num text-fg">{counts[s]}</span>
                  </Link>
                ) : null,
              )}
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {active.map((s) => (
                <StudyCard key={s.slug} s={s} compact />
              ))}
            </div>
          </>
        )}
      </Card>

      <Card className="mt-4">
        <CardTitle right={<More to="/backtests">All backtests</More>}>Recently saved backtests</CardTitle>
        {runs.isLoading ? (
          <Loading />
        ) : (
          <div className="divide-y divide-line">
            {recent.map((r) => (
              <Link key={r.run_id} to={`/backtests/${encodeURIComponent(r.run_id)}`} className="flex items-center gap-4 py-2.5 hover:bg-hover/50 sm:-mx-2 sm:px-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-medium text-fg">{r.name}</div>
                  <div className="num truncate text-[11px] text-faint">
                    {r.created?.slice(0, 10)} · {r.start?.slice(0, 10)} → {r.end?.slice(0, 10)}
                  </div>
                </div>
                <div className="num hidden w-20 text-right text-[13px] sm:block">
                  <span className={tone(r.CAGR)}>{pct(r.CAGR)}</span>
                  <div className="text-[10.5px] text-faint">CAGR</div>
                </div>
                <div className="num w-16 text-right text-[13px]">
                  {fixed(r.Sharpe)}
                  <div className="text-[10.5px] text-faint">Sharpe</div>
                </div>
                <div className="num w-16 text-right text-[13px] text-neg">
                  {pct(r["max DD"], 0)}
                  <div className="text-[10.5px] text-faint">max DD</div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
