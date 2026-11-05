import clsx from "clsx";
import { ExternalLink, Search } from "lucide-react";
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { usePapers, useStudies, type Status, type StudySummary } from "../lib/api";
import { Callout, Card, DataTable, Empty, ErrorState, Loading, PageHeader, STATUS, StatusBadge, Tabs, Tag } from "../components/ui";

export function StudyCard({ s, compact }: { s: StudySummary; compact?: boolean }) {
  return (
    <Link
      to={`/research/${s.slug}`}
      className="group flex h-full flex-col rounded-xl border border-line bg-panel p-4 transition-colors hover:border-line-strong hover:bg-panel-2"
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <h3 className="text-[14px] font-semibold leading-snug tracking-tight text-fg group-hover:text-accent">{s.name}</h3>
        <StatusBadge status={s.status} className="shrink-0" />
      </div>
      <p className={clsx("text-[13px] leading-relaxed text-muted", compact ? "line-clamp-2" : "line-clamp-3")}>{s.verdict}</p>
      <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-3">
        {s.tags.slice(0, 4).map((t) => (
          <Tag key={t}>{t}</Tag>
        ))}
        {!!s.children?.length && <span className="text-[11px] text-faint">+{s.children.length} follow-ups</span>}
        {s.start && s.end && (
          <span className="num ml-auto text-[11px] text-faint">
            {s.start.slice(0, 7)} → {s.end.slice(0, 7)}
          </span>
        )}
      </div>
    </Link>
  );
}

function Papers({ query }: { query: string }) {
  const q = usePapers();
  const rows = useMemo(() => {
    if (!q.data) return null;
    const ql = query.toLowerCase();
    const keep = q.data.rows.filter((r) => !ql || r.join(" ").toLowerCase().includes(ql));
    return { ...q.data, rows: keep, total: keep.length };
  }, [q.data, query]);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  if (!rows) return null;
  return (
    <>
      <p className="mb-3 text-sm text-muted">Every link cited in a research note, with the notes that cite it.</p>
      <DataTable
        data={rows}
        maxHeight={null}
        pageSize={300}
        columns={[
          {
            key: "title",
            render: (v, r) => (
              <a href={String(r.url)} target="_blank" rel="noreferrer" className="inline-flex max-w-[560px] items-center gap-1 truncate text-accent hover:underline">
                <span className="truncate">{String(v)}</span>
                <ExternalLink className="size-3 shrink-0 opacity-60" />
              </a>
            ),
          },
          { key: "source", render: (v) => <span className="text-muted">{String(v ?? "")}</span> },
          { key: "cited in", render: (v) => <span className="block max-w-[380px] truncate text-muted">{String(v)}</span> },
        ]}
      />
    </>
  );
}

export function ResearchPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "papers" ? "papers" : "studies";
  const query = params.get("q") ?? "";
  const status = (params.get("status") as Status | null) ?? null;
  const tag = params.get("tag");
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p, { replace: true });
  };
  const q = useStudies();
  const top = useMemo(() => (q.data?.studies ?? []).filter((s) => !s.parent), [q.data]);
  const tags = useMemo(() => {
    const c = new Map<string, number>();
    top.forEach((s) => s.tags.forEach((t) => c.set(t, (c.get(t) ?? 0) + 1)));
    return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 14);
  }, [top]);
  const filtered = useMemo(() => {
    const ql = query.toLowerCase();
    return top.filter(
      (s) =>
        (!status || s.status === status) &&
        (!tag || s.tags.includes(tag)) &&
        (!ql || `${s.name} ${s.verdict} ${s.tags.join(" ")} ${s.slug}`.toLowerCase().includes(ql)),
    );
  }, [top, status, tag, query]);

  const counts = useMemo(() => {
    const c: Partial<Record<Status, number>> = {};
    top.forEach((s) => (c[s.status] = (c[s.status] ?? 0) + 1));
    return c;
  }, [top]);

  return (
    <>
      <PageHeader
        title="Research"
        sub={
          <>
            Every study is a folder in <code className="num text-fg">research/</code> with a README (verdict first) and a{" "}
            <code className="num text-fg">result.json</code>. Status and verdict come from there.
          </>
        }
      />
      <Tabs
        value={tab}
        onChange={(v) => set("tab", v === "studies" ? null : v)}
        tabs={[
          { value: "studies", label: `Studies${top.length ? ` (${top.length})` : ""}` },
          { value: "papers", label: "Papers" },
        ]}
      />
      <div className="mb-5 flex flex-col gap-3">
        <label className="relative block max-w-md">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-faint" />
          <input
            value={query}
            onChange={(e) => set("q", e.target.value || null)}
            placeholder={tab === "papers" ? "Search papers, e.g. momentum, Lopez-Lira" : "Search studies, e.g. ORB, slippage, LLM"}
            className="h-9 w-full rounded-lg border border-line bg-panel pl-8 pr-3 text-[13px] text-fg outline-none placeholder:text-faint focus:border-accent"
          />
        </label>
        {tab === "studies" && q.data && (
          <>
            <div className="flex flex-wrap gap-1.5">
              <Tag active={!status} onClick={() => set("status", null)}>
                All · {top.length}
              </Tag>
              {q.data.statuses
                .filter((s) => counts[s])
                .map((s) => (
                  <Tag key={s} active={status === s} onClick={() => set("status", status === s ? null : s)}>
                    <span className={clsx("mr-1.5 size-1.5 rounded-full", STATUS[s].dot)} />
                    {STATUS[s].label} · {counts[s]}
                  </Tag>
                ))}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {tags.map(([t, n]) => (
                <Tag key={t} active={tag === t} onClick={() => set("tag", tag === t ? null : t)}>
                  #{t} <span className="ml-1 text-faint">{n}</span>
                </Tag>
              ))}
            </div>
          </>
        )}
      </div>

      {tab === "papers" ? (
        <Papers query={query} />
      ) : q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorState error={q.error} />
      ) : (
        <div className="space-y-8">
          {!!q.data?.problems.length && (
            <Callout tone="warn">
              <div className="mb-1 font-semibold">Format problems</div>
              <ul className="list-disc pl-5 text-muted">
                {q.data.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </Callout>
          )}
          {!filtered.length && <Empty>No study matches these filters.</Empty>}
          {(q.data?.statuses ?? []).map((st) => {
            const group = filtered.filter((s) => s.status === st);
            if (!group.length) return null;
            return (
              <section key={st}>
                <div className="mb-3 flex items-center gap-2">
                  <StatusBadge status={st} />
                  <span className="text-xs text-faint">{group.length}</span>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {group.map((s) => (
                    <StudyCard key={s.slug} s={s} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
      {tab === "studies" && <Card className="mt-10" pad>
        <div className="text-[13px] text-muted">
          Add a study: create <code className="num text-fg">research/&lt;slug&gt;/README.md</code> and a{" "}
          <code className="num text-fg">result.json</code> with <code className="num text-fg">status</code> and{" "}
          <code className="num text-fg">verdict</code>, then run{" "}
          <code className="num text-fg">uv run python -m horizon_trader.results.index</code>.
        </div>
      </Card>}
    </>
  );
}
