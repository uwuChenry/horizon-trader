import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  PriceScaleMode,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import clsx from "clsx";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Candle, Point } from "../lib/api";
import { useTheme, tokens, SERIES } from "../lib/theme";

const ts = (t: number) => t as UTCTimestamp;

export type Line = {
  name: string;
  points: Point[];
  color?: string;
  kind?: "line" | "area" | "histogram";
  width?: number;
  dashed?: boolean;
};

type Fmt = "money" | "pct" | "ratio" | "num";

function formatter(fmt: Fmt) {
  return (v: number) => {
    if (fmt === "money") {
      const a = Math.abs(v);
      return (v < 0 ? "-$" : "$") + (a >= 10000 ? (a / 1000).toFixed(a >= 100000 ? 0 : 1) + "k" : a.toFixed(a >= 100 ? 0 : 2));
    }
    if (fmt === "pct") return (v * 100).toFixed(1) + "%";
    if (fmt === "ratio") return v.toFixed(2) + "x";
    return v.toFixed(2);
  };
}

function baseOptions(intraday: boolean) {
  const k = tokens();
  return {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: k.muted,
      fontFamily: "Inter Variable, system-ui, sans-serif",
      fontSize: 11,
      attributionLogo: false,
      panes: { separatorColor: k.border, separatorHoverColor: k.border },
    },
    grid: { vertLines: { color: k.grid }, horzLines: { color: k.grid } },
    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.06 } },
    timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false, fixLeftEdge: true, fixRightEdge: true },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: k.faint, labelBackgroundColor: k.border, width: 1 as const, style: LineStyle.Dashed },
      horzLine: { color: k.faint, labelBackgroundColor: k.border, width: 1 as const, style: LineStyle.Dashed },
    },
    handleScroll: { vertTouchDrag: false },
  };
}

function useChart(height: number, intraday: boolean, build: (chart: IChartApi) => void, deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null);
  const { resolved } = useTheme();
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, baseOptions(intraday));
    build(chart);
    chart.timeScale().fitContent();
    return () => chart.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolved, intraday, ...deps]);
  return <div ref={ref} style={{ height }} className="w-full" />;
}

/** Line/area time series with an HTML legend that tracks the crosshair. */
export function TimeChart({
  lines,
  height = 320,
  fmt = "money",
  log = false,
  intraday = false,
  markers,
  zeroLine,
  title,
  right,
}: {
  lines: Line[];
  height?: number;
  fmt?: Fmt;
  log?: boolean;
  intraday?: boolean;
  markers?: { t: number; text: string }[];
  zeroLine?: boolean;
  title?: ReactNode;
  right?: ReactNode;
}) {
  const [hover, setHover] = useState<Record<string, number> | null>(null);
  const colored = useMemo(
    () => lines.map((l, i) => ({ ...l, color: l.color ?? SERIES[i % SERIES.length] })),
    [lines],
  );
  const chart = useChart(
    height,
    intraday,
    (chart) => {
      const k = tokens();
      chart.applyOptions({
        rightPriceScale: { mode: log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal },
        localization: { priceFormatter: formatter(fmt) },
      });
      const series: { name: string; s: ISeriesApi<SeriesType> }[] = [];
      colored.forEach((l, i) => {
        const data = l.points.map((p) => ({ time: ts(p.t), value: p.v }));
        let s: ISeriesApi<SeriesType>;
        if (l.kind === "area") {
          s = chart.addSeries(AreaSeries, {
            lineColor: l.color,
            topColor: l.color + "00",
            bottomColor: l.color + "55",
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
            invertFilledArea: true,
          } as never);
        } else if (l.kind === "histogram") {
          s = chart.addSeries(HistogramSeries, { color: l.color, priceLineVisible: false, lastValueVisible: false });
        } else {
          s = chart.addSeries(LineSeries, {
            color: l.color,
            lineWidth: (l.width ?? (i === 0 ? 2 : 1.5)) as never,
            lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid,
            priceLineVisible: false,
            lastValueVisible: i === 0,
            crosshairMarkerRadius: 3,
          });
        }
        s.setData(data);
        series.push({ name: l.name, s });
        if (i === 0 && zeroLine) s.createPriceLine({ price: 0, color: k.faint, lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: false, title: "" });
      });
      if (markers?.length && series[0] && colored[0].points.length) {
        const times = colored[0].points.map((p) => p.t);
        const snap = (t: number) => times[Math.max(0, times.findIndex((x) => x >= t))] ?? times[times.length - 1];
        createSeriesMarkers(
          series[0].s,
          markers.map((m) => ({ time: ts(snap(m.t)), position: "aboveBar", shape: "arrowDown", color: k.faint, text: m.text })) as SeriesMarker<Time>[],
        );
      }
      chart.subscribeCrosshairMove((p) => {
        if (!p.time) return setHover(null);
        const out: Record<string, number> = {};
        for (const { name, s } of series) {
          const d = p.seriesData.get(s) as { value?: number } | undefined;
          if (d?.value !== undefined) out[name] = d.value;
        }
        setHover(out);
      });
    },
    [colored, log, fmt, markers, zeroLine, height],
  );
  const f = formatter(fmt);
  const last = (l: Line) => l.points[l.points.length - 1]?.v;
  return (
    <div>
      {(title || right || colored.length > 1) && (
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
            {title && <div className="text-[13px] font-semibold text-fg">{title}</div>}
            {colored.length > 1 || hover
              ? colored.slice(0, 8).map((l) => (
                  <span key={l.name} className="inline-flex items-center gap-1.5 text-xs text-muted">
                    <span className="h-0.5 w-3 rounded-full" style={{ background: l.color }} />
                    <span className="max-w-56 truncate">{l.name}</span>
                    <span className="num text-fg">{f(hover?.[l.name] ?? last(l) ?? NaN)}</span>
                  </span>
                ))
              : null}
          </div>
          {right}
        </div>
      )}
      {chart}
    </div>
  );
}

export type PriceLine = { price: number; color: string; title: string; dashed?: boolean };
export type Mark = { t: number; text: string; color: string; position: "aboveBar" | "belowBar"; shape: "arrowUp" | "arrowDown" | "circle" };

/** TradingView-style candles, optional volume pane, trade markers and level lines. */
export function CandleChart({
  candles,
  height = 440,
  intraday = true,
  lines = [],
  marks = [],
  volume = false,
}: {
  candles: Candle[];
  height?: number;
  intraday?: boolean;
  lines?: PriceLine[];
  marks?: Mark[];
  volume?: boolean;
}) {
  return useChart(
    height,
    intraday,
    (chart) => {
      const k = tokens();
      const up = "#26a69a";
      const down = "#ef5350";
      const s = chart.addSeries(CandlestickSeries, {
        upColor: up,
        downColor: down,
        borderVisible: false,
        wickUpColor: up,
        wickDownColor: down,
        priceLineVisible: false,
      });
      s.setData(candles.map((c) => ({ time: ts(c.t), open: c.o, high: c.h, low: c.l, close: c.c })));
      for (const l of lines) {
        s.createPriceLine({
          price: l.price,
          color: l.color,
          lineWidth: 1,
          lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid,
          axisLabelVisible: true,
          title: l.title,
        });
      }
      if (marks.length) {
        const times = candles.map((c) => c.t);
        const snap = (t: number) => {
          let best = times[0];
          for (const x of times) if (x <= t) best = x;
          return best;
        };
        createSeriesMarkers(
          s,
          [...marks]
            .sort((a, b) => a.t - b.t)
            .map((m) => ({ time: ts(snap(m.t)), position: m.position, shape: m.shape, color: m.color, text: m.text, size: 1.2 })) as SeriesMarker<Time>[],
        );
      }
      if (volume && candles.some((c) => c.v !== undefined)) {
        const v = chart.addSeries(
          HistogramSeries,
          { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false },
          1,
        );
        v.setData(
          candles.map((c) => ({ time: ts(c.t), value: c.v ?? 0, color: (c.c >= c.o ? up : down) + "66" })),
        );
        const panes = chart.panes();
        panes[0]?.setStretchFactor(0.78);
        panes[1]?.setStretchFactor(0.22);
      }
      chart.applyOptions({ grid: { vertLines: { color: k.grid }, horzLines: { color: k.grid } } });
    },
    [candles, lines, marks, volume, height],
  );
}

/** Bins with negative bins in red and positive in green. edges.length = counts.length + 1. */
export function Histogram({
  edges,
  counts,
  height = 200,
  unit = "",
}: {
  edges: number[];
  counts: number[];
  height?: number;
  unit?: string;
}) {
  const max = Math.max(1, ...counts);
  const [hover, setHover] = useState<number | null>(null);
  if (!counts.length) return null;
  return (
    <div>
      <div className="flex items-end gap-px" style={{ height }}>
        {counts.map((c, i) => {
          const mid = (edges[i] + edges[i + 1]) / 2;
          return (
            <div
              key={i}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              className={clsx("flex-1 rounded-t-[2px] transition-opacity", mid >= 0 ? "bg-pos" : "bg-neg", hover !== null && hover !== i && "opacity-50")}
              style={{ height: `${(c / max) * 100}%`, minHeight: c ? 1 : 0 }}
            />
          );
        })}
      </div>
      <div className="num mt-1.5 flex justify-between text-[11px] text-faint">
        <span>
          {edges[0].toFixed(1)}
          {unit}
        </span>
        <span className="text-muted">
          {hover !== null
            ? `${edges[hover].toFixed(2)} to ${edges[hover + 1].toFixed(2)}${unit}: ${counts[hover].toLocaleString()}`
            : `${counts.reduce((a, b) => a + b, 0).toLocaleString()} observations`}
        </span>
        <span>
          {edges[edges.length - 1].toFixed(1)}
          {unit}
        </span>
      </div>
    </div>
  );
}

/** Histogram of raw values (client-side binning). */
export function ValueHistogram({ values, bins = 50, height = 200, unit = "" }: { values: number[]; bins?: number; height?: number; unit?: string }) {
  const { edges, counts } = useMemo(() => {
    const v = values.filter((x) => Number.isFinite(x));
    if (!v.length) return { edges: [], counts: [] };
    let lo = Math.min(...v);
    let hi = Math.max(...v);
    // keep the long tails from flattening everything: clip to the 1st-99th percentile
    const s = [...v].sort((a, b) => a - b);
    lo = Math.min(lo, 0, s[Math.floor(s.length * 0.01)]);
    hi = Math.max(hi > 0 ? s[Math.ceil(s.length * 0.99) - 1] : hi, 0);
    if (hi === lo) hi = lo + 1;
    const w = (hi - lo) / bins;
    const edges = Array.from({ length: bins + 1 }, (_, i) => lo + i * w);
    const counts = new Array(bins).fill(0);
    for (const x of v) counts[Math.min(bins - 1, Math.max(0, Math.floor((x - lo) / w)))] += 1;
    return { edges, counts };
  }, [values, bins]);
  return <Histogram edges={edges} counts={counts} height={height} unit={unit} />;
}

/** Horizontal bars for categories, coloured by sign. */
export function Bars({
  rows,
  format,
}: {
  rows: { label: string; value: number; note?: string; tone?: "pos" | "neg" }[];
  format: (v: number) => string;
}) {
  const max = Math.max(1e-12, ...rows.map((r) => Math.abs(r.value)));
  const anyNeg = rows.some((r) => r.value < 0);
  return (
    <div className="space-y-1">
      {rows.map((r) => (
        <div key={r.label} className="grid grid-cols-[minmax(4rem,9rem)_1fr_auto] items-center gap-3 text-xs">
          <div className="truncate text-muted" title={r.label}>
            {r.label}
          </div>
          <div className="relative h-5">
            {anyNeg && <div className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />}
            <div
              className={clsx("absolute inset-y-0.5 rounded-sm", (r.tone ?? (r.value >= 0 ? "pos" : "neg")) === "pos" ? "bg-pos/80" : "bg-neg/80")}
              style={
                anyNeg
                  ? r.value >= 0
                    ? { left: "50%", width: `${(r.value / max) * 50}%` }
                    : { right: "50%", width: `${(-r.value / max) * 50}%` }
                  : { left: 0, width: `${(r.value / max) * 100}%` }
              }
            />
          </div>
          <div className="num w-28 text-right text-fg">
            {format(r.value)}
            {r.note && <span className="ml-1.5 text-faint">{r.note}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Scatter plot in SVG (e.g. MAE vs MFE). */
export function Scatter({
  points,
  height = 300,
  xLabel,
  yLabel,
}: {
  points: { x: number; y: number; good: boolean }[];
  height?: number;
  xLabel: string;
  yLabel: string;
}) {
  const pts = points.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (!pts.length) return null;
  const q = (arr: number[], p: number) => [...arr].sort((a, b) => a - b)[Math.floor((arr.length - 1) * p)];
  const xs = pts.map((p) => p.x);
  const ys = pts.map((p) => p.y);
  const [x0, x1] = [Math.min(0, q(xs, 0.005)), Math.max(0, q(xs, 0.995))];
  const [y0, y1] = [Math.min(0, q(ys, 0.005)), Math.max(0, q(ys, 0.995))];
  const W = 600;
  const H = height;
  const pad = 28;
  const sx = (x: number) => pad + ((Math.min(Math.max(x, x0), x1) - x0) / (x1 - x0 || 1)) * (W - pad - 8);
  const sy = (y: number) => H - pad - ((Math.min(Math.max(y, y0), y1) - y0) / (y1 - y0 || 1)) * (H - pad - 8);
  const sample = pts.length > 4000 ? pts.filter((_, i) => i % Math.ceil(pts.length / 4000) === 0) : pts;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`${yLabel} vs ${xLabel}`}>
      <line x1={sx(0)} x2={sx(0)} y1={8} y2={H - pad} stroke="var(--border-strong)" />
      <line x1={pad} x2={W - 8} y1={sy(0)} y2={sy(0)} stroke="var(--border-strong)" />
      {sample.map((p, i) => (
        <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={2.6} fill={p.good ? "var(--pos)" : "var(--neg)"} opacity={0.55} />
      ))}
      <text x={W - 8} y={H - 8} textAnchor="end" fontSize={11} fill="var(--muted)">
        {xLabel} →
      </text>
      <text x={pad + 4} y={16} fontSize={11} fill="var(--muted)">
        ↑ {yLabel}
      </text>
    </svg>
  );
}

/** Calendar-style monthly returns grid. */
export function MonthlyHeatmap({
  months,
  rows,
}: {
  months: string[];
  rows: { year: number; values: (number | null)[]; total: number | null }[];
}) {
  const all = rows.flatMap((r) => r.values).filter((v): v is number => v !== null);
  const lim = Math.max(0.01, ...all.map(Math.abs));
  const bg = (v: number | null) => {
    if (v === null) return "transparent";
    const a = Math.min(1, Math.abs(v) / lim) * 0.75 + 0.08;
    return `color-mix(in srgb, ${v >= 0 ? "var(--pos)" : "var(--neg)"} ${Math.round(a * 100)}%, transparent)`;
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-separate border-spacing-0.5 text-[11.5px]">
        <thead>
          <tr>
            <th className="px-1 py-1 text-left font-medium text-faint" />
            {months.map((m) => (
              <th key={m} className="px-1 py-1 font-medium text-faint">
                {m}
              </th>
            ))}
            <th className="px-1 py-1 font-semibold text-muted">Year</th>
          </tr>
        </thead>
        <tbody>
          {[...rows].reverse().map((r) => (
            <tr key={r.year}>
              <td className="num pr-2 text-muted">{r.year}</td>
              {r.values.map((v, i) => (
                <td key={i} className="num rounded-[4px] px-1 py-1.5 text-center text-fg" style={{ background: bg(v) }} title={v === null ? "" : `${(v * 100).toFixed(2)}%`}>
                  {v === null ? "" : (v * 100).toFixed(1)}
                </td>
              ))}
              <td className={clsx("num px-1 py-1.5 text-center font-semibold", r.total !== null && (r.total >= 0 ? "text-pos" : "text-neg"))}>
                {r.total === null ? "" : (r.total * 100).toFixed(1) + "%"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Tiny inline trend line. */
export function Sparkline({ points, height = 36, className }: { points: Point[]; height?: number; className?: string }) {
  if (points.length < 2) return null;
  const W = 200;
  const vs = points.map((p) => p.v);
  const lo = Math.min(...vs);
  const hi = Math.max(...vs);
  const d = points
    .map((p, i) => `${i ? "L" : "M"}${((i / (points.length - 1)) * W).toFixed(1)},${(height - 2 - ((p.v - lo) / (hi - lo || 1)) * (height - 4)).toFixed(1)}`)
    .join("");
  const up = vs[vs.length - 1] >= vs[0];
  return (
    <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" className={clsx("w-full", className)} style={{ height }}>
      <path d={d} fill="none" stroke={up ? "var(--pos)" : "var(--neg)"} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
