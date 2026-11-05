import { ExternalLink } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router-dom";

/** Join a relative link onto the directory of `base` ("research/a/README.md" + "../b/x.md"). */
export function resolveRef(base: string, rel: string): string | null {
  const parts = base.split("/").slice(0, -1);
  for (const seg of decodeURIComponent(rel).split("/")) {
    if (seg === "" || seg === ".") continue;
    if (seg === "..") {
      if (!parts.length) return null;
      parts.pop();
    } else parts.push(seg);
  }
  return parts.join("/");
}

/** Where a repo path opens in the app, or null if the dashboard doesn't serve it. */
export function routeFor(ref: string): string | null {
  if (!ref.startsWith("research/")) return null;
  const readme = ref.match(/^research\/(.+)\/README\.md$/);
  if (readme) return `/research/${readme[1]}`;
  if (ref.endsWith(".md")) return `/doc?ref=${encodeURIComponent(ref)}`;
  if (/\.(csv|json|jsonl|parquet|html|xml|txt)$/i.test(ref)) return `/file?ref=${encodeURIComponent(ref)}`;
  return null;
}

export function Markdown({ text, base }: { text: string; base: string }) {
  return (
    <div className="report prose prose-sm max-w-none sm:prose-base prose-headings:tracking-tight prose-h1:text-2xl prose-h2:mt-10 prose-h2:text-lg prose-h3:text-base prose-p:leading-relaxed prose-li:my-0.5 prose-table:my-4">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href = "", children }) => {
            if (/^(https?:|mailto:)/.test(href))
              return (
                <a href={href} target="_blank" rel="noreferrer noopener" className="inline-flex items-baseline gap-0.5">
                  {children}
                  <ExternalLink className="relative top-px size-3 shrink-0 opacity-60" />
                </a>
              );
            if (href.startsWith("#")) return <a href={href}>{children}</a>;
            const [path, frag] = href.split("#");
            const ref = resolveRef(base, path);
            const to = ref ? routeFor(ref) : null;
            if (!to)
              return (
                <span className="text-muted" title={ref ? `${ref} (not served by the dashboard)` : href}>
                  {children}
                </span>
              );
            return <Link to={to + (frag ? `#${frag}` : "")}>{children}</Link>;
          },
          img: ({ src, alt }) => {
            const ref = typeof src === "string" && !/^https?:/.test(src) ? resolveRef(base, src) : null;
            const url = ref ? `/api/files/raw?ref=${encodeURIComponent(ref)}` : (src as string);
            return <img src={url} alt={alt ?? ""} className="rounded-lg border border-line" />;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
