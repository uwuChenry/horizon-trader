import clsx from "clsx";
import { ChevronRight, FileCode2, FileText, LineChart, Table2, FileJson, Globe } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArtifactView } from "../components/Artifact";
import { Markdown } from "../components/Markdown";
import { Card, Empty, ErrorState, Loading, StatusBadge, Tabs, Tag, STATUS } from "../components/ui";
import { useDoc, useStudy, type Artifact } from "../lib/api";
import { bytes } from "../lib/format";
import { StudyCard } from "./Research";

const ROLE_ICON: Record<string, typeof Table2> = {
  equity: LineChart,
  chart: Globe,
  metadata: FileJson,
  verification: FileCode2,
  report: FileText,
};

const VERDICT_BORDER: Record<string, string> = {
  core: "border-l-pos",
  candidate: "border-l-accent",
  running: "border-l-violet",
  inconclusive: "border-l-warn",
  idea: "border-l-faint",
  reference: "border-l-faint",
  dead: "border-l-neg",
};

function DocInline({ docRef }: { docRef: string }) {
  const q = useDoc(docRef);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  return q.data ? <Markdown text={q.data.markdown} base={q.data.ref} /> : null;
}

function DataTab({ artifacts, selected, onSelect }: { artifacts: Artifact[]; selected: string | null; onSelect: (r: string) => void }) {
  if (!artifacts.length) return <Empty>This study has no data files.</Empty>;
  const current = artifacts.find((a) => a.ref === selected) ?? artifacts.find((a) => a.role === "equity") ?? artifacts[0];
  return (
    <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
      <div className="flex max-h-[640px] flex-col gap-0.5 overflow-auto lg:sticky lg:top-6">
        {artifacts.map((a) => {
          const Icon = ROLE_ICON[a.role] ?? Table2;
          return (
            <button
              key={a.ref}
              onClick={() => onSelect(a.ref)}
              className={clsx(
                "flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition-colors",
                a.ref === current.ref ? "bg-accent-soft text-accent" : "text-muted hover:bg-hover hover:text-fg",
              )}
            >
              <Icon className="size-3.5 shrink-0" />
              <span className="min-w-0 flex-1 truncate">{a.label}</span>
              <span className="num shrink-0 text-[10.5px] text-faint">{bytes(a.bytes)}</span>
            </button>
          );
        })}
      </div>
      <Card className="min-w-0">
        <ArtifactView key={current.ref} artifact={current} />
      </Card>
    </div>
  );
}

export function StudyPage() {
  const slug = useParams()["*"] ?? "";
  const [params, setParams] = useSearchParams();
  const q = useStudy(slug);
  const set = (k: string, v: string | null, extra?: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [kk, vv] of Object.entries({ [k]: v, ...extra })) {
      if (vv) p.set(kk, vv);
      else p.delete(kk);
    }
    setParams(p, { replace: true });
  };
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const s = q.data!;
  const tab = (params.get("tab") as "report" | "docs" | "data" | "subs") ?? "report";
  const crumbs = slug.split("/");
  return (
    <>
      <nav className="mb-4 flex flex-wrap items-center gap-1 text-xs text-muted">
        <Link to="/research" className="hover:text-fg">
          Research
        </Link>
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-1">
            <ChevronRight className="size-3 text-faint" />
            {i < crumbs.length - 1 ? (
              <Link to={`/research/${crumbs.slice(0, i + 1).join("/")}`} className="hover:text-fg">
                {c}
              </Link>
            ) : (
              <span className="text-fg">{c}</span>
            )}
          </span>
        ))}
      </nav>

      <div className="mb-6">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <StatusBadge status={s.status} />
          <span className="text-xs text-faint">{s.kind === "note" ? "note" : s.kind === "forward" ? "forward test" : "study"}</span>
        </div>
        <h1 className="max-w-4xl text-xl font-semibold tracking-tight text-fg sm:text-2xl">{s.name}</h1>
        <div className={clsx("mt-4 max-w-4xl rounded-r-lg border-l-[3px] bg-panel py-3 pl-4 pr-4 text-[14px] leading-relaxed text-fg", VERDICT_BORDER[s.status])}>
          <div className="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-faint">Verdict</div>
          {s.verdict}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted">
          {s.start && s.end && (
            <span>
              Period <span className="num text-fg">{s.start}</span> → <span className="num text-fg">{s.end}</span>
            </span>
          )}
          {s.updated && (
            <span>
              Updated <span className="num text-fg">{s.updated}</span>
            </span>
          )}
          <span className="flex flex-wrap gap-1.5">
            {s.tags.map((t) => (
              <Link key={t} to={`/research?tag=${t}`}>
                <Tag>#{t}</Tag>
              </Link>
            ))}
          </span>
        </div>
        {!!s.code.length && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {s.code.map((c) => (
              <code key={c} className="num rounded-md border border-line bg-panel-2 px-1.5 py-0.5 text-[11px] text-muted">
                {c}
              </code>
            ))}
          </div>
        )}
        {s.description && <p className="mt-3 max-w-4xl text-[13px] text-muted">{s.description}</p>}
      </div>

      <Tabs
        value={tab}
        onChange={(v) => set("tab", v === "report" ? null : v)}
        tabs={[
          { value: "report", label: "Report" },
          { value: "docs", label: `Documents (${s.docs.length})`, hidden: !s.docs.length },
          { value: "data", label: `Data (${s.artifacts.length})`, hidden: !s.artifacts.length },
          { value: "subs", label: `Follow-ups (${s.children.length})`, hidden: !s.children.length },
        ]}
      />

      {tab === "report" &&
        (s.report ? (
          <Card className="max-w-4xl sm:px-8 sm:py-7">
            <Markdown text={s.report.markdown} base={s.report.ref} />
          </Card>
        ) : (
          <Empty>No README.md yet.</Empty>
        ))}

      {tab === "docs" && (
        <div className="grid gap-5 lg:grid-cols-[240px_1fr]">
          <div className="flex flex-col gap-0.5">
            {s.docs.map((d) => {
              const active = (params.get("doc") ?? s.docs[0].ref) === d.ref;
              return (
                <button
                  key={d.ref}
                  onClick={() => set("doc", d.ref)}
                  className={clsx(
                    "rounded-lg px-2.5 py-2 text-left transition-colors",
                    active ? "bg-accent-soft" : "hover:bg-hover",
                  )}
                >
                  <div className={clsx("truncate text-[12.5px] font-medium", active ? "text-accent" : "text-fg")}>{d.title}</div>
                  <div className="num truncate text-[11px] text-faint">{d.name}</div>
                </button>
              );
            })}
          </div>
          <Card className="min-w-0 sm:px-8 sm:py-7">
            <DocInline docRef={params.get("doc") ?? s.docs[0].ref} />
          </Card>
        </div>
      )}

      {tab === "data" && <DataTab artifacts={s.artifacts} selected={params.get("artifact")} onSelect={(r) => set("artifact", r)} />}

      {tab === "subs" && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {s.children.map((c) => (
            <StudyCard key={c.slug} s={c} />
          ))}
        </div>
      )}
      <div className="sr-only">{STATUS[s.status]?.label}</div>
    </>
  );
}
