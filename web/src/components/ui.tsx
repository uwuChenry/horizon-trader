import clsx from "clsx";
import { AlertTriangle, ArrowDown, ArrowUp, ChevronsUpDown, Loader2 } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import type { Status, Table } from "../lib/api";
import { cellText } from "../lib/format";

export function Card({
  children,
  className,
  pad = true,
}: {
  children: ReactNode;
  className?: string;
  pad?: boolean;
}) {
  return (
    <div className={clsx("rounded-xl border border-line bg-panel", pad && "p-4 sm:p-5", className)}>
      {children}
    </div>
  );
}

export function CardTitle({ children, right, sub }: { children: ReactNode; right?: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mb-3 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-[13px] font-semibold tracking-tight text-fg">{children}</h3>
        {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

export function PageHeader({
  title,
  sub,
  right,
  eyebrow,
}: {
  title: ReactNode;
  sub?: ReactNode;
  right?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5 text-xs font-medium text-muted">{eyebrow}</div>}
        <h1 className="text-xl font-semibold tracking-tight text-fg sm:text-2xl">{title}</h1>
        {sub && <div className="mt-1.5 max-w-3xl text-sm text-muted">{sub}</div>}
      </div>
      {right && <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

export function Kpi({
  label,
  value,
  sub,
  tone,
  hint,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: string;
  hint?: string;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-line bg-panel px-4 py-3" title={hint}>
      <div className="truncate text-[11px] font-medium uppercase tracking-wider text-faint">{label}</div>
      <div className={clsx("num mt-1 truncate text-lg font-semibold text-fg sm:text-xl", tone)}>{value}</div>
      {sub && <div className="mt-0.5 truncate text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function KpiRow({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-8">{children}</div>;
}

export const STATUS: Record<Status, { label: string; cls: string; dot: string }> = {
  core: { label: "Core", cls: "bg-pos-soft text-pos", dot: "bg-pos" },
  candidate: { label: "Candidate", cls: "bg-accent-soft text-accent", dot: "bg-accent" },
  running: { label: "Running", cls: "bg-[color-mix(in_srgb,var(--violet)_14%,transparent)] text-violet", dot: "bg-violet" },
  inconclusive: { label: "Inconclusive", cls: "bg-warn-soft text-warn", dot: "bg-warn" },
  idea: { label: "Idea", cls: "bg-panel-2 text-muted", dot: "bg-muted" },
  reference: { label: "Reference", cls: "bg-panel-2 text-muted", dot: "bg-faint" },
  dead: { label: "Dead", cls: "bg-neg-soft text-neg", dot: "bg-neg" },
};

export function StatusBadge({ status, className }: { status: Status; className?: string }) {
  const s = STATUS[status] ?? STATUS.reference;
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold", s.cls, className)}>
      <span className={clsx("size-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

export function Tag({ children, active, onClick }: { children: ReactNode; active?: boolean; onClick?: () => void }) {
  const El = onClick ? "button" : "span";
  return (
    <El
      onClick={onClick}
      className={clsx(
        "inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium transition-colors",
        active ? "border-accent/50 bg-accent-soft text-accent" : "border-line text-muted",
        onClick && !active && "hover:border-line-strong hover:text-fg",
      )}
    >
      {children}
    </El>
  );
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  size = "md",
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className="inline-flex max-w-full overflow-x-auto rounded-lg border border-line bg-panel-2 p-0.5">
      {options.map((o) => (
        <button
          key={String(o.value)}
          onClick={() => onChange(o.value)}
          className={clsx(
            "rounded-md font-medium transition-colors",
            size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-[13px]",
            o.value === value ? "bg-panel text-fg shadow-sm ring-1 ring-line" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  tabs,
  onChange,
}: {
  value: T;
  tabs: { value: T; label: ReactNode; hidden?: boolean }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="-mx-4 mb-5 overflow-x-auto border-b border-line px-4 sm:mx-0 sm:px-0">
      <div className="flex gap-1">
        {tabs
          .filter((t) => !t.hidden)
          .map((t) => (
            <button
              key={t.value}
              onClick={() => onChange(t.value)}
              className={clsx(
                "relative whitespace-nowrap px-3 py-2.5 text-[13px] font-medium transition-colors",
                t.value === value ? "text-fg" : "text-muted hover:text-fg",
              )}
            >
              {t.label}
              {t.value === value && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />}
            </button>
          ))}
      </div>
    </div>
  );
}

export function Select({
  value,
  onChange,
  options,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={clsx(
        "h-8 rounded-lg border border-line bg-panel px-2.5 text-[13px] text-fg outline-none transition-colors hover:border-line-strong focus:border-accent",
        className,
      )}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Button({
  children,
  onClick,
  active,
  disabled,
  title,
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
  title?: string;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={clsx(
        "inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        active
          ? "border-accent/50 bg-accent-soft text-accent"
          : "border-line bg-panel text-fg hover:border-line-strong hover:bg-hover",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-16 text-sm text-muted">
      <Loader2 className="size-4 animate-spin" /> {label}…
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-neg/30 bg-neg-soft px-4 py-3 text-sm text-neg">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>{error instanceof Error ? error.message : String(error)}</span>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-line px-4 py-10 text-center text-sm text-muted">{children}</div>;
}

export function Callout({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" | "bad" }) {
  return (
    <div
      className={clsx(
        "rounded-xl border px-4 py-3 text-sm",
        tone === "info" && "border-accent/25 bg-accent-soft text-fg",
        tone === "warn" && "border-warn/30 bg-warn-soft text-fg",
        tone === "bad" && "border-neg/30 bg-neg-soft text-fg",
      )}
    >
      {children}
    </div>
  );
}

/** Two-column key/value list, e.g. a stats table. */
export function StatList({ rows }: { rows: [string, ReactNode, string?][] }) {
  return (
    <dl className="divide-y divide-line">
      {rows.map(([k, v, cls]) => (
        <div key={k} className="flex items-baseline justify-between gap-4 py-1.5 text-[13px]">
          <dt className="text-muted">{k}</dt>
          <dd className={clsx("num text-right text-fg", cls)}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

type Col = {
  key: string;
  label?: string;
  render?: (v: unknown, row: Record<string, unknown>) => ReactNode;
  align?: "left" | "right";
  className?: string;
};

/** A sortable table over a {columns, rows} payload (or explicit columns), with sticky header. */
export function DataTable({
  data,
  columns,
  maxHeight = 480,
  onRowClick,
  selected,
  pageSize = 200,
  dense,
  rowClass,
}: {
  data: Table;
  columns?: Col[];
  maxHeight?: number | null;
  onRowClick?: (index: number, row: Record<string, unknown>) => void;
  selected?: number | null;
  pageSize?: number;
  dense?: boolean;
  rowClass?: (row: Record<string, unknown>) => string | undefined;
}) {
  const cols: Col[] = columns ?? data.columns.map((c) => ({ key: c }));
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [limit, setLimit] = useState(pageSize);
  const objects = useMemo(
    () => data.rows.map((r, i) => ({ i, o: Object.fromEntries(data.columns.map((c, j) => [c, r[j]])) })),
    [data],
  );
  const sorted = useMemo(() => {
    if (!sort) return objects;
    const out = [...objects];
    out.sort((a, b) => {
      const x = a.o[sort.key];
      const y = b.o[sort.key];
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : 1) * sort.dir;
    });
    return out;
  }, [objects, sort]);
  const numeric = (k: string) => objects.slice(0, 50).some((r) => typeof r.o[k] === "number");
  const shown = sorted.slice(0, limit);
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div className="overflow-auto" style={maxHeight ? { maxHeight } : undefined}>
        <table className="w-full border-collapse text-[12.5px]">
          <thead className="sticky top-0 z-10 bg-panel-2">
            <tr>
              {cols.map((c) => {
                const right = c.align ? c.align === "right" : numeric(c.key);
                const active = sort?.key === c.key;
                return (
                  <th
                    key={c.key}
                    onClick={() =>
                      setSort(active ? (sort!.dir === -1 ? { key: c.key, dir: 1 } : null) : { key: c.key, dir: -1 })
                    }
                    className={clsx(
                      "cursor-pointer select-none whitespace-nowrap border-b border-line px-3 py-2 font-medium text-muted hover:text-fg",
                      right ? "text-right" : "text-left",
                    )}
                  >
                    <span className="inline-flex items-center gap-1">
                      {c.label ?? c.key}
                      {active ? (
                        sort!.dir === -1 ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />
                      ) : (
                        <ChevronsUpDown className="size-3 opacity-30" />
                      )}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map(({ i, o }) => (
              <tr
                key={i}
                onClick={onRowClick ? () => onRowClick(i, o) : undefined}
                className={clsx(
                  "border-b border-line/60 last:border-0",
                  onRowClick && "cursor-pointer hover:bg-hover",
                  selected === i && "bg-accent-soft",
                  rowClass?.(o),
                )}
              >
                {cols.map((c) => {
                  const v = o[c.key];
                  const right = c.align ? c.align === "right" : typeof v === "number";
                  return (
                    <td
                      key={c.key}
                      className={clsx(
                        "whitespace-nowrap px-3 text-fg",
                        dense ? "py-1" : "py-1.5",
                        right && "num text-right",
                        c.className,
                      )}
                    >
                      {c.render ? c.render(v, o) : cellText(c.key, v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(sorted.length > limit || data.total > data.rows.length) && (
        <div className="flex items-center justify-between border-t border-line bg-panel-2 px-3 py-1.5 text-xs text-muted">
          <span>
            Showing {shown.length.toLocaleString()} of {data.total.toLocaleString()} rows
          </span>
          {sorted.length > limit && (
            <button className="font-medium text-accent hover:underline" onClick={() => setLimit((l) => l + pageSize * 5)}>
              Show more
            </button>
          )}
        </div>
      )}
    </div>
  );
}
