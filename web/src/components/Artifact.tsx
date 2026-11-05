import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { rawUrl, useFileEquity, useFileTable, type Artifact } from "../lib/api";
import { TimeChart } from "./charts";
import { Button, DataTable, ErrorState, Loading, Segmented } from "./ui";

function TableView({ fileRef }: { fileRef: string }) {
  const q = useFileTable(fileRef);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  return q.data ? <DataTable data={q.data} maxHeight={560} dense /> : null;
}

function TextView({ fileRef, json }: { fileRef: string; json: boolean }) {
  const q = useQuery({
    queryKey: ["raw", fileRef],
    queryFn: async () => {
      const r = await fetch(rawUrl(fileRef));
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const text = await r.text();
      if (!json) return text;
      try {
        return JSON.stringify(JSON.parse(text), null, 2);
      } catch {
        return text;
      }
    },
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <pre className="num max-h-[560px] overflow-auto rounded-lg border border-line bg-panel-2 p-4 text-[12px] leading-relaxed text-fg">
      {q.data}
    </pre>
  );
}

function EquityView({ fileRef }: { fileRef: string }) {
  const q = useFileEquity(fileRef);
  const [log, setLog] = useState(false);
  if (q.isLoading) return <Loading />;
  if (q.error || !q.data?.series.length) return <TableView fileRef={fileRef} />;
  return (
    <TimeChart
      lines={q.data.series.map((s) => ({ name: s.name, points: s.points }))}
      log={log}
      height={380}
      right={
        <div className="flex items-center gap-2">
          {q.data.total > q.data.series.length && (
            <span className="text-xs text-faint">
              first {q.data.series.length} of {q.data.total} series
            </span>
          )}
          <Segmented size="sm" value={log ? "log" : "lin"} onChange={(v) => setLog(v === "log")} options={[{ value: "lin", label: "Linear" }, { value: "log", label: "Log" }]} />
        </div>
      }
    />
  );
}

export function ArtifactView({ artifact }: { artifact: Pick<Artifact, "ref" | "role" | "suffix" | "label"> }) {
  const { ref, role, suffix } = artifact;
  let body;
  if (suffix === ".html")
    body = <iframe src={rawUrl(ref)} sandbox="allow-scripts" className="h-[620px] w-full rounded-lg border border-line bg-white" title={artifact.label} />;
  else if (role === "equity" && (suffix === ".csv" || suffix === ".parquet")) body = <EquityView fileRef={ref} />;
  else if (suffix === ".csv" || suffix === ".parquet") body = <TableView fileRef={ref} />;
  else if (suffix === ".jsonl") body = <TableView fileRef={ref} />;
  else body = <TextView fileRef={ref} json={suffix === ".json"} />;
  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="num min-w-0 truncate text-xs text-muted">{ref}</div>
        <a href={rawUrl(ref)} download>
          <Button>
            <Download className="size-3.5" /> Download
          </Button>
        </a>
      </div>
      {body}
    </div>
  );
}
