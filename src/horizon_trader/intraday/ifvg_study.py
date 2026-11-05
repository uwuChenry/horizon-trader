"""Run the frozen IFVG experiment on existing local SPY/QQQ caches only.

    python -m horizon_trader.intraday.ifvg_study

Results are automatically discoverable in the dashboard's Results catalog.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.config import REPO_ROOT, data_dir
from horizon_trader.intraday import ifvg as S
from horizon_trader.results.catalog import write_manifest

STUDY = "ifvg_2026_10_18"
PERIODS = ("all", "2021-23", "2024+")
COSTS = ("gross", "net", "stress")
TARGETS = (1.0, 2.0, 3.0)
TICKERS = ("SPY", "QQQ")


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load_sessions(root: Path) -> tuple[dict, pd.DatetimeIndex, pd.DataFrame, list]:
    """Strict common-calendar QC, explicitly logged rather than silently filled."""
    groups, inputs, skipped = {}, [], []
    for ticker in TICKERS:
        path = root / "massive" / "derived" / f"minute_{ticker}.parquet"
        b = pd.read_parquet(path, columns=["ts", "open", "high", "low", "close"])
        if b.ts.dt.tz is None:
            raise ValueError(f"{ticker}: naive timestamps")
        b["ts"] = b.ts.dt.tz_convert(S.TZ)
        b["date"] = b.ts.dt.tz_localize(None).dt.normalize()
        groups[ticker] = {
            d: g.sort_values("ts").reset_index(drop=True) for d, g in b.groupby("date", sort=True)
        }
        inputs.append(
            dict(
                path=str(path),
                sha256=digest(path),
                rows=len(b),
                start=str(b.ts.min()),
                end=str(b.ts.max()),
            )
        )
    sessions = {}
    for date in sorted(set(groups["SPY"]) | set(groups["QQQ"])):
        spy = groups["SPY"].get(date)
        start = date.tz_localize(S.TZ) + pd.Timedelta(minutes=570)
        if spy is None:
            skipped.append(dict(date=date, ticker="SPY", reason="missing_session"))
            continue
        last = (spy.ts.max() - start) / S.MINUTE
        length = 390 if last == 389 else 210 if last in (209, 210, 211) else None
        if length is None:
            skipped.append(dict(date=date, ticker="SPY", reason=f"unknown_session_end:{last}"))
            continue
        end = start + pd.Timedelta(minutes=length)
        expected = pd.date_range(start, periods=length, freq="min")
        valid = {}
        for ticker in TICKERS:
            b = groups[ticker].get(date)
            reason = None
            if b is None:
                reason = "missing_session"
            else:
                b = b[(b.ts >= start) & (b.ts < end)].reset_index(drop=True)
                values = b[["open", "high", "low", "close"]].to_numpy()
                if not pd.DatetimeIndex(b.ts).equals(expected):
                    reason = "missing_duplicate_or_off_grid_minutes"
                elif (
                    not np.isfinite(values).all()
                    or (values <= 0).any()
                    or (b.high < b[["open", "close", "low"]].max(axis=1)).any()
                    or (b.low > b[["open", "close", "high"]].min(axis=1)).any()
                ):
                    reason = "invalid_ohlc"
            if reason:
                skipped.append(dict(date=date, ticker=ticker, reason=reason))
            else:
                valid[ticker] = b
        if len(valid) == len(TICKERS):
            sessions[date] = (valid, end - S.MINUTE)
    if not sessions:
        raise ValueError("No complete common sessions")
    return (
        sessions,
        pd.DatetimeIndex(sorted(sessions)),
        pd.DataFrame(skipped, columns=["date", "ticker", "reason"]),
        inputs,
    )


def period_dates(calendar, period):
    if period == "2021-23":
        return calendar[calendar < "2024-01-01"]
    if period == "2024+":
        return calendar[calendar >= "2024-01-01"]
    return calendar


def uncertainty(daily: pd.DataFrame, samples=2000, block=20) -> pd.DataFrame:
    """Paired session blocks preserve flat days and contemporaneous dependence."""
    rng = np.random.default_rng(20261018)
    rows = []
    primary = daily[(daily.cost_case == "net") & (daily.target_r == 2)]
    for (ticker, period), frame in primary.groupby(["ticker", "period"], sort=True):
        returns = frame.pivot(index="date", columns="strategy", values="return").sort_index()
        n = len(returns)
        if n < block * 2:
            continue
        starts = rng.integers(0, n, size=(samples, ceil_div(n, block)))
        idx = ((starts[:, :, None] + np.arange(block)) % n).reshape(samples, -1)[:, :n]
        for name in ("ifvg_close", "ifvg_retest"):
            control = name.replace("ifvg", "breakout")
            for comparison, series in (
                ("zero", returns[name]),
                (control, returns[name] - returns[control]),
            ):
                values = series.to_numpy()
                lo, hi = np.quantile(values[idx].mean(axis=1), [0.025, 0.975])
                rows.append(
                    dict(
                        ticker=ticker,
                        period=period,
                        strategy=name,
                        comparison=comparison,
                        mean_daily_bps=values.mean() * 10000,
                        ci95_low_bps=lo * 10000,
                        ci95_high_bps=hi * 10000,
                        samples=samples,
                        block_sessions=block,
                    )
                )
    return pd.DataFrame(rows)


def ceil_div(n, d):
    return (n + d - 1) // d


def markdown_table(frame: pd.DataFrame) -> str:
    # No optional tabulate dependency needed for a portable report.
    cells = [[str(x) for x in row] for row in frame.itertuples(index=False, name=None)]
    return "\n".join(
        [
            "| " + " | ".join(frame.columns) + " |",
            "| " + " | ".join(["---"] * len(frame.columns)) + " |",
            *("| " + " | ".join(row) + " |" for row in cells),
        ]
    )


def report(out, table, intervals, calendar, skipped, paths):
    primary = table[(table.target_r == 2) & (table.cost_case == "net")].copy()
    display = primary[
        [
            "ticker",
            "strategy",
            "period",
            "trades",
            "cagr",
            "sharpe",
            "max_drawdown",
            "avg_pnl",
            "profit_factor",
        ]
    ].copy()
    for key in ("cagr", "max_drawdown"):
        display[key] = display[key].map(lambda v: f"{v:.1%}")
    for key in ("sharpe", "avg_pnl", "profit_factor"):
        display[key] = display[key].map(lambda v: f"{v:.2f}")
    both = primary[primary.strategy.str.startswith("ifvg") & (primary.period != "all")]
    positive_both = both.groupby(["ticker", "strategy"]).total_return.agg(lambda x: (x > 0).all())
    text = f"""# IFVG strategy backtest

Data: {calendar[0].date()}–{calendar[-1].date()}, {len(calendar):,} common complete
sessions; {skipped.date.nunique()} excluded dates ({len(skipped)} instrument/date
issues). SPY and QQQ are tested as **separate $5,000 accounts**. These results
do not represent a combined portfolio or an NQ/ES futures test.

Rules were written in [protocol.md](protocol.md) before the first performance
run. Five-minute gap inversions, long and short, maximum one trade a day, entries
through 11:30 ET; stop beyond the zone, primary 2R target, flat before close.
Entry is at the next minute open after a completed signal. The retest variant
requires a later completed rejection candle. Position size includes stop
slippage and fees, risks at most 1% before stop gaps, and uses at most 1x capital.

## Primary results: Tiered fees and one cent per share each side

{markdown_table(display)}

Of the four IFVG instrument/entry combinations, **{int(positive_both.sum())} were
profitable in both chronological periods** at the primary 2R/net assumptions.
This is a descriptive screen, not a significance test or a recommendation.
The 2024+ period and the earlier period each restart at $5,000. History has
already been reused by other strategies; neither is a pristine holdout.

## Evidence and reproducibility

- [All 216 configuration/period/cost rows](metrics.csv): gross, Tiered/1c,
  Tiered/3c; 1R, 2R, 3R; all four triggers and both ETFs.
- [Primary equity paths](equity.csv), [yearly returns](annual_returns.csv),
  [long/short and exit breakdown](trade_breakdown.csv).
- [Block-bootstrap intervals](uncertainty.csv): 20-session blocks, 2,000 draws.
  Mean daily returns and paired differences versus the corresponding breakout
  control. Unadjusted descriptive 95% intervals; not independent-trade tests.
- [Data exclusions](skipped_sessions.csv), [source/data hashes](manifest.json).
- Full trade paths, all sized fills, daily account paths and a standalone
  interactive equity/drawdown chart are registered in this study's Results entry
  under `data/{STUDY}/`. The report CSVs contain derived results, not raw bars.

Run from the repository root:

```bash
python -m horizon_trader.intraday.ifvg_study
pytest tests/test_ifvg.py
```

The runner reads only existing caches and refuses to fetch data. The original
run used an isolated Linux environment at `/tmp/horizon-ifvg-venv`, installed
from the repository lockfile. Temporary environments need recreation after cleanup.

## Interpretation and limitations

The breakout controls use the same timing and account rules but different event
times and stop widths. They benchmark an alternative trigger; their difference
does not causally isolate IFVG. Parameters were not optimized, and all 24
instrument/strategy/target configurations are reported.

Minute-bar exits use stop-first treatment when both barriers are touched;
`ambiguous` counts these cases. Stops gapped through fill at the worse open.
Targets get no favorable gap improvement and pay the same slippage allowance.
Slippage is assumed, not measured from quotes. The report includes gross P&L
on the exact net positions as well as separately compounded zero-cost accounts.

Sharpe uses a zero cash hurdle, with no cash interest. The fixed repository fee
schedule is applied across history. Borrow/locates, short-sale restrictions,
taxes, subscriptions, broker margin and settlement are not modeled. Strict
complete-session screening removes some days retrospectively; exclusions are
explicit and identical across configurations. Session ends use the existing
SPY-coverage proxy. One trade is selected per day before sizing; zero-share
trades are skipped without searching for a replacement.

These are historical simulations. A favorable row would still need genuinely
new forward observations and execution checks before being treated as an edge.
"""
    (out / "report.md").write_text(text, encoding="utf-8")


def chart(daily, dest):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=2,
        cols=2,
        shared_xaxes=True,
        subplot_titles=(
            "SPY: $5,000 accounts",
            "QQQ: $5,000 accounts",
            "SPY drawdown",
            "QQQ drawdown",
        ),
    )
    colors = dict(zip(S.STRATEGIES, ("#0072B2", "#D55E00", "#009E73", "#CC79A7"), strict=True))
    for col, ticker in enumerate(TICKERS, 1):
        for name in S.STRATEGIES:
            d = daily[
                (daily.ticker == ticker)
                & (daily.strategy == name)
                & (daily.target_r == 2)
                & (daily.cost_case == "net")
                & (daily.period == "all")
            ]
            dates = [d.date.iloc[0] - pd.Timedelta(days=1), *d.date]
            equity = np.r_[5000, d.equity]
            dd = equity / np.maximum.accumulate(equity) - 1
            for row, values in ((1, equity), (2, dd)):
                fig.add_trace(
                    go.Scatter(
                        x=dates,
                        y=values,
                        name=name,
                        legendgroup=name,
                        line=dict(color=colors[name]),
                        showlegend=(row == col == 1),
                    ),
                    row=row,
                    col=col,
                )
    fig.update_yaxes(tickformat=".0%", row=2)
    fig.update_layout(
        title="IFVG: 2R, Tiered + 1c/side, independent accounts",
        template="plotly_white",
        height=850,
    )
    fig.write_html(dest, include_plotlyjs=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "research" / STUDY)
    args = parser.parse_args()
    out = args.output
    protocol = out / "protocol.md"
    if not protocol.exists():
        raise ValueError("Write/freeze protocol.md in the output directory before running")
    artifact_dir = data_dir() / STUDY
    artifact_dir.mkdir(parents=True, exist_ok=True)
    rules = S.Rules()
    manifest = dict(
        started_at=datetime.now(UTC).isoformat(),
        rules=asdict(rules),
        targets=TARGETS,
        costs=COSTS,
        tickers=TICKERS,
        capital=5000,
        protocol_sha256=digest(protocol),
        source_hashes={
            p.name: digest(p)
            for p in (
                Path(__file__),
                Path(S.__file__),
                REPO_ROOT / "uv.lock",
                REPO_ROOT / "src/horizon_trader/execution/costs.py",
            )
        },
    )
    print("Loading local snapshots and validating common sessions...", flush=True)
    sessions, calendar, skipped, inputs = load_sessions(data_dir())
    manifest.update(inputs=inputs, sessions=len(calendar), excluded_dates=skipped.date.nunique())
    skipped.to_csv(out / "skipped_sessions.csv", index=False)
    paths = []
    for j, (_date, (bars, exit_time)) in enumerate(sessions.items(), 1):
        for ticker, minutes in bars.items():
            candles = S.candles(minutes, rules)
            for strategy in S.STRATEGIES:
                decisions = S.signals(candles, strategy, rules)
                for target in TARGETS:
                    trade = S.simulate_day(minutes, decisions, strategy, target, exit_time, rules)
                    if trade:
                        paths.append({**trade, "ticker": ticker})
        if j % 200 == 0 or j == len(sessions):
            print(f"Simulated {j}/{len(sessions)} sessions", flush=True)
    paths = pd.DataFrame(paths)
    paths.to_parquet(artifact_dir / "trade_paths.parquet", index=False)
    all_daily, all_fills, summary = [], [], []
    for ticker in TICKERS:
        for strategy in S.STRATEGIES:
            for target in TARGETS:
                selected = paths[
                    (paths.ticker == ticker)
                    & (paths.strategy == strategy)
                    & (paths.target_r == target)
                ]
                for period in PERIODS:
                    dates = period_dates(calendar, period)
                    if dates.empty:
                        continue
                    trades = selected[selected.date.isin(dates)]
                    for cost in COSTS:
                        daily, fills = S.account(trades, dates, cost)
                        meta = dict(
                            ticker=ticker,
                            strategy=strategy,
                            target_r=target,
                            period=period,
                            cost_case=cost,
                        )
                        summary.append({**meta, **S.metrics(daily, fills)})
                        all_daily.append(daily.assign(**meta))
                        if len(fills):
                            all_fills.append(fills.assign(**meta))
    table = pd.DataFrame(summary)
    daily = pd.concat(all_daily, ignore_index=True)
    fills = pd.concat(all_fills, ignore_index=True) if all_fills else pd.DataFrame()
    table.to_csv(out / "metrics.csv", index=False)
    daily.to_parquet(artifact_dir / "daily.parquet", index=False)
    fills.to_parquet(artifact_dir / "fills.parquet", index=False)
    primary = daily[(daily.target_r == 2) & (daily.cost_case == "net") & (daily.period == "all")]
    wide = primary.assign(series=primary.ticker + "_" + primary.strategy).pivot(
        index="date", columns="series", values="equity"
    )
    initial = pd.DataFrame(5000.0, index=[calendar[0] - pd.Timedelta(days=1)], columns=wide.columns)
    pd.concat([initial, wide]).rename_axis("date").to_csv(out / "equity.csv")
    annual = (
        primary.assign(year=primary.date.dt.year)
        .groupby(["ticker", "strategy", "year"], as_index=False)["return"]
        .agg(lambda r: (1 + r).prod() - 1)
    )
    annual.to_csv(out / "annual_returns.csv", index=False)
    if len(fills):
        f = fills[(fills.target_r == 2) & (fills.cost_case == "net") & (fills.period == "all")]
        breakdown = f.groupby(["ticker", "strategy", "side", "exit_reason"], as_index=False).agg(
            trades=("pnl", "size"),
            pnl=("pnl", "sum"),
            mean_pnl=("pnl", "mean"),
            mean_gross_R=("gross_R", "mean"),
            ambiguous=("ambiguous", "sum"),
        )
        breakdown.to_csv(out / "trade_breakdown.csv", index=False)
    intervals = uncertainty(daily)
    intervals.to_csv(out / "uncertainty.csv", index=False)
    chart(daily, artifact_dir / "equity.html")
    manifest.update(
        finished_at=datetime.now(UTC).isoformat(),
        simulated_paths=len(paths),
        rows=len(table),
        output_hashes={
            p.name: digest(p)
            for p in (
                out / "metrics.csv",
                artifact_dir / "trade_paths.parquet",
                artifact_dir / "fills.parquet",
                artifact_dir / "daily.parquet",
            )
        },
    )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report(out, table, intervals, calendar, skipped, paths)
    write_manifest(
        out / "result.json",
        id=f"research:{STUDY}",
        kind="research",
        name="IFVG: mechanical gap inversions on SPY and QQQ",
        description="Frozen five-minute rules, breakout controls, costs and chronological checks.",
        start=str(calendar[0].date()),
        end=str(calendar[-1].date()),
        include=["*.md", "*.csv", "*.json"],
        artifacts=[
            dict(path=f"data:{STUDY}/{name}", role=role, label=label)
            for name, role, label in (
                ("trade_paths.parquet", "trades", "Raw simulated round trips"),
                ("fills.parquet", "trades", "All sized round trips after costs"),
                ("daily.parquet", "table", "All independent daily accounts"),
                ("equity.html", "chart", "Standalone equity and drawdown chart"),
            )
        ],
    )
    print(
        table[(table.target_r == 2) & (table.cost_case == "net")].to_string(index=False), flush=True
    )
    print(f"Report: {out / 'report.md'}", flush=True)


if __name__ == "__main__":
    main()
