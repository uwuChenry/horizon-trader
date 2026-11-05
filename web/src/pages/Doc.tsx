import { ChevronRight } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { ArtifactView } from "../components/Artifact";
import { Markdown } from "../components/Markdown";
import { Card, ErrorState, Loading } from "../components/ui";
import { useDoc } from "../lib/api";

function Crumbs({ refPath, study }: { refPath: string; study?: string | null }) {
  return (
    <nav className="mb-4 flex flex-wrap items-center gap-1 text-xs text-muted">
      <Link to="/research" className="hover:text-fg">
        Research
      </Link>
      {study && (
        <>
          <ChevronRight className="size-3 text-faint" />
          <Link to={`/research/${study}`} className="hover:text-fg">
            {study}
          </Link>
        </>
      )}
      <ChevronRight className="size-3 text-faint" />
      <span className="num text-fg">{refPath.split("/").pop()}</span>
    </nav>
  );
}

export function DocPage() {
  const [params] = useSearchParams();
  const ref = params.get("ref");
  const q = useDoc(ref);
  if (!ref) return <ErrorState error="No document given" />;
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <>
      <Crumbs refPath={ref} study={q.data?.study} />
      <Card className="max-w-4xl sm:px-8 sm:py-7">
        <Markdown text={q.data!.markdown} base={q.data!.ref} />
      </Card>
    </>
  );
}

export function FilePage() {
  const [params] = useSearchParams();
  const ref = params.get("ref") ?? "";
  const suffix = "." + (ref.split(".").pop() ?? "");
  const name = ref.split("/").pop() ?? ref;
  const parts = ref.replace(/^research\//, "").split("/");
  const study = parts.length > 1 ? parts.slice(0, -1).join("/") : null;
  const role = /equity|_daily$/.test(name.replace(/\.\w+$/, "")) ? "equity" : "table";
  return (
    <>
      <Crumbs refPath={ref} study={study} />
      <Card>
        <ArtifactView artifact={{ ref, role, suffix, label: name }} />
      </Card>
    </>
  );
}
