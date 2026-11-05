import { ChevronRight } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { TimeChart } from "../components/charts";
import { Callout, Card, DataTable, Empty, ErrorState, Loading, PageHeader } from "../components/ui";
import { useCompare } from "../lib/api";
import { stat } from "../lib/format";

const KEYS = ["CAGR", "Sharpe", "Sortino", "max DD", "vol", "Calmar", "total return", "trades", "win rate", "profit factor", "expectancy $", "costs"];

export function ComparePage() {
  const [params] = useSearchParams();
  const ids = (params.get("ids") ?? "").split(",").filter(Boolean);
  const q = useCompare(ids);
  if (!ids.length) return <Empty>Pick runs on the Backtests page to compare.</Empty>;
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const runs = q.data!.runs;
  const table = {
    columns: ["metric", ...runs.map((r) => r.name)],
    rows: KEYS.filter((k) => runs.some((r) => r.stats[k] !== undefined)).map((k) => [k, ...runs.map((r) => r.stats[k] ?? null)]),
    total: KEYS.length,
  };
  return (
    <>
      <nav className="mb-4 flex items-center gap-1 text-xs text-muted">
        <Link to="/backtests" className="hover:text-fg">
          Backtests
        </Link>
        <ChevronRight className="size-3 text-faint" />
        <span className="text-fg">Compare</span>
      </nav>
      <PageHeader title="Compare runs" sub="Growth of $1 on a log scale." />
      <Card className="mb-4">
        <TimeChart lines={runs.map((r) => ({ name: r.name, points: r.growth }))} log fmt="ratio" height={420} />
      </Card>
      <Callout>Different runs can cover different date ranges: compare over matching periods before drawing conclusions.</Callout>
      <div className="mt-4">
        <DataTable
          data={table}
          maxHeight={null}
          columns={table.columns.map((c, i) => ({
            key: c,
            render: i === 0 ? undefined : (v: unknown, r: Record<string, unknown>) => <span className="num">{stat(String(r.metric), v)}</span>,
          }))}
        />
      </div>
    </>
  );
}
