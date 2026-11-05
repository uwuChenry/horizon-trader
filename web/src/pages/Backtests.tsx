import clsx from "clsx";
import { GitCompareArrows, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, DataTable, ErrorState, Loading, PageHeader, Select } from "../components/ui";
import { useRuns } from "../lib/api";
import { fixed, pct, tone } from "../lib/format";

export function BacktestsPage() {
  const q = useRuns();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const strategy = params.get("strategy") ?? "";
  const [picked, setPicked] = useState<string[]>([]);
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p, { replace: true });
  };
  const strategies = useMemo(
    () => [...new Set((q.data?.runs ?? []).map((r) => r.strategy).filter(Boolean) as string[])].sort(),
    [q.data],
  );
  const rows = useMemo(() => {
    const ql = query.toLowerCase();
    return (q.data?.runs ?? []).filter(
      (r) =>
        (!strategy || r.strategy === strategy) &&
        (!ql || `${r.name} ${r.strategy} ${r.run_id}`.toLowerCase().includes(ql)),
    );
  }, [q.data, query, strategy]);
  const table = useMemo(
    () => ({
      columns: ["pick", "name", "strategy", "start", "end", "CAGR", "Sharpe", "max DD", "trades", "created", "run_id", "holdings"],
      rows: rows.map((r) => [
        picked.includes(r.run_id), r.name, r.strategy, r.start?.slice(0, 10), r.end?.slice(0, 10), r.CAGR ?? null,
        r.Sharpe ?? null, r["max DD"] ?? null, r.trades ?? null, r.created?.slice(0, 16).replace("T", " "), r.run_id, r.holdings,
      ]),
      total: rows.length,
    }),
    [rows, picked],
  );
  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= 6 ? p : [...p, id]));

  return (
    <>
      <PageHeader
        title="Backtests"
        sub={
          <>
            Saved runs under <code className="num text-fg">data/results</code>. Create more with <code className="num text-fg">--save</code> on any backtest
            command. Sharpe uses a 0% risk-free rate.
          </>
        }
        right={
          <Button disabled={picked.length < 1} onClick={() => nav(`/backtests/compare?ids=${picked.map(encodeURIComponent).join(",")}`)}>
            <GitCompareArrows className="size-3.5" /> Compare{picked.length ? ` (${picked.length})` : ""}
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="relative block w-full max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-faint" />
          <input
            value={query}
            onChange={(e) => set("q", e.target.value)}
            placeholder="Search runs"
            className="h-8 w-full rounded-lg border border-line bg-panel pl-8 pr-3 text-[13px] text-fg outline-none placeholder:text-faint focus:border-accent"
          />
        </label>
        <Select
          value={strategy}
          onChange={(v) => set("strategy", v)}
          options={[{ value: "", label: "All strategies" }, ...strategies.map((s) => ({ value: s, label: s.length > 60 ? s.slice(0, 60) + "…" : s }))]}
          className="max-w-xs"
        />
        <span className="text-xs text-faint">{rows.length} runs</span>
      </div>
      {q.isLoading ? (
        <Loading label="Reading bundles" />
      ) : q.error ? (
        <ErrorState error={q.error} />
      ) : (
        <DataTable
          data={table}
          maxHeight={null}
          onRowClick={(_, r) => nav(`/backtests/${encodeURIComponent(String(r.run_id))}`)}
          columns={[
            {
              key: "pick",
              label: "",
              render: (v, r) => (
                <input
                  type="checkbox"
                  checked={!!v}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => toggle(String(r.run_id))}
                  className="size-3.5 accent-[var(--accent)]"
                  title="Select to compare"
                />
              ),
            },
            {
              key: "name",
              render: (v, r) => (
                <div className="max-w-[420px]">
                  <div className="truncate font-medium text-fg">{String(v)}</div>
                  <div className="truncate text-[11px] text-faint">{String(r.strategy ?? "")}</div>
                </div>
              ),
            },
            { key: "start", render: (v) => <span className="num text-muted">{String(v ?? "")}</span> },
            { key: "end", render: (v) => <span className="num text-muted">{String(v ?? "")}</span> },
            { key: "CAGR", align: "right", render: (v) => <span className={clsx("num", tone(v))}>{pct(v)}</span> },
            { key: "Sharpe", align: "right", render: (v) => <span className="num">{fixed(v)}</span> },
            { key: "max DD", align: "right", render: (v) => <span className="num text-neg">{pct(v)}</span> },
            { key: "trades", align: "right" },
            { key: "created", render: (v) => <span className="num text-[11.5px] text-faint">{String(v ?? "")}</span> },
          ]}
        />
      )}
    </>
  );
}
