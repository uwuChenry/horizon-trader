"""Run the fixed competitor-pairs protocol and publish reproducible research artifacts.

    .venv/Scripts/python.exe research/pairs_2026_10_12/prepare.py
    .venv/Scripts/python.exe research/pairs_2026_10_12/run.py

No network requests, parameter search, or broker connections in this runner.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from horizon_trader.backtest.analytics import equity_stats, monthly_returns
from horizon_trader.backtest.bundle import save_run
from horizon_trader.backtest.pairs import EXPANDED, PRIMARY, PairConfig, load_data, simulate
from horizon_trader.results.catalog import write_manifest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "data/pairs_2026_10_12"
PERIODS = {
    "Full 2017-2026": ("2017-01-03", "2026-10-09"),
    "2017-2023": ("2017-01-03", "2023-12-31"),
    "2024-2025": ("2024-01-01", "2025-12-31"),
    "2026 YTD": ("2026-01-01", "2026-10-09"),
}
COST_COLS = ["commission", "slippage", "borrow", "withholding", "financing"]


def stats(result):
    eq = result.daily.equity
    s = equity_stats(eq)
    t = result.trades
    return {
        "return": s["total return"],
        "cagr": s["CAGR"],
        "sharpe_zero_rf": s["Sharpe"],
        "max_dd": s["max DD"],
        "ending_equity": eq.iloc[-1],
        "trades": len(t),
        "win_rate": (t.pnl > 0).mean() if len(t) else np.nan,
        "average_trade_pnl": t.pnl.mean() if len(t) else np.nan,
        "average_gross_exposure": result.daily.gross.iloc[1:].mean(),
        "max_gross_exposure": result.daily.gross.max(),
        "rejected": len(result.rejected),
        "open_pairs": len(result.open_positions),
        **{f"{k}_dollars": result.daily[k].sum() for k in COST_COLS},
    }


def table(df, pct=(), dollars=()):
    f = df.copy()
    for col in f:
        if col in pct:
            f[col] = f[col].map(lambda x: f"{x:+.2%}")
        elif col in dollars:
            f[col] = f[col].map(lambda x: f"${x:,.2f}")
        elif pd.api.types.is_float_dtype(f[col]):
            f[col] = f[col].map(lambda x: f"{x:.2f}")
    return "\n".join(
        [
            "| " + " | ".join(f.columns) + " |",
            "| " + " | ".join(["---"] * len(f.columns)) + " |",
            *(
                "| " + " | ".join(map(str, row)) + " |"
                for row in f.itertuples(index=False, name=None)
            ),
        ]
    )


def block_interval(eq, seed=20261012):
    r = eq.pct_change().dropna().to_numpy()
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(r), size=(2000, int(np.ceil(len(r) / 20))))
    ix = (starts[:, :, None] + np.arange(20)) % len(r)
    sample = r[ix.reshape(2000, -1)[:, : len(r)]]
    lo, hi = np.quantile(sample.mean(axis=1) * 252, [0.025, 0.975])
    return dict(
        annualized_mean_low=float(lo),
        annualized_mean_high=float(hi),
        block_sessions=20,
        draws=2000,
        seed=seed,
    )


def publish_bundle(name, equity, trades, meta, benchmark, tables):
    """Refresh this experiment's own bundles on rerun, preserving their stable IDs."""
    audit_path = HERE / "verification.json"
    old = json.loads(audit_path.read_text()).get("bundles", []) if audit_path.exists() else []
    for ref in old:
        folder = (ROOT / ref).resolve()
        if not folder.is_relative_to((ROOT / "data/results").resolve()):
            raise ValueError("Bundle path escapes results folder")
        meta_path = folder / "meta.json"
        if not meta_path.exists():
            continue
        previous = json.loads(meta_path.read_text())
        if previous.get("name") != name:
            continue
        equity.rename("equity").to_frame().to_parquet(folder / "equity.parquet")
        trades.to_parquet(folder / "trades.parquet", index=False)
        benchmark.rename("benchmark").to_frame().to_parquet(folder / "benchmark.parquet")
        for key, frame in tables.items():
            frame.to_parquet(folder / "tables" / f"{key.replace('_', '-')}.parquet", index=False)
        previous.update(meta)
        meta_path.write_text(json.dumps(previous, indent=2, default=str) + "\n", encoding="utf-8")
        return folder
    return save_run(name, equity, trades, meta, benchmark, tables)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((DATA / "raw/manifest.json").read_text())
    for row in manifest["files"]:
        digest = hashlib.sha256((DATA / "raw" / f"{row['symbol']}.parquet").read_bytes())
        if digest.hexdigest() != row["sha256"]:
            raise ValueError(f"Frozen data hash mismatch: {row['symbol']}")
    b = load_data(DATA / "raw")
    base = PairConfig()
    variants = {
        "Base net": base,
        "Before all costs": replace(
            base, plan="zero", slippage_bps=0, borrow_rate=0, withholding=0, debit_rate=0
        ),
        "1 bp fills": replace(base, slippage_bps=1),
        "10 bp fills": replace(base, slippage_bps=10),
        "0.25% borrow": replace(base, borrow_rate=0.0025),
        "3% borrow": replace(base, borrow_rate=0.03),
        "10% borrow": replace(base, borrow_rate=0.10),
        "Fixed commissions": replace(base, plan="fixed"),
        "$100k capital": replace(base, capital=100_000),
        "Fractional diagnostic": replace(base, whole_shares=False),
        "40-day lookback": replace(base, lookback=40),
        "90-day lookback": replace(base, lookback=90),
        "1.5 z entry": replace(base, entry_z=1.5),
        "2.5 z entry": replace(base, entry_z=2.5),
        "20-session cap": replace(base, max_hold=20),
        "60-session cap": replace(base, max_hold=60),
        "Correlation >= 0.6": replace(base, min_correlation=0.6),
        "Expanded five pairs": replace(base, pairs=EXPANDED),
        **{f"{a}/{c} alone": replace(base, pairs=((a, c),)) for a, c in PRIMARY},
    }
    settings = {name: asdict(cfg) for name, cfg in variants.items()}
    (HERE / "settings.json").write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    summary, saved = [], {}
    for name, cfg in variants.items():
        for period, (start, end) in PERIODS.items():
            result = simulate(b, cfg, start, end)
            summary.append(dict(variant=name, period=period, **stats(result)))
            if name in ("Base net", "Before all costs"):
                saved[name, period] = result
        print(f"Completed {name}", flush=True)
    summary = pd.DataFrame(summary)
    summary.to_csv(HERE / "summary.csv", index=False)
    net = saved["Base net", "Full 2017-2026"]
    gross = saved["Before all costs", "Full 2017-2026"]
    for label, r in (("net", net), ("gross", gross)):
        r.daily.to_csv(DATA / f"{label}_daily.csv")
        r.trades.to_csv(HERE / f"{label}_trades.csv", index=False)
        r.fills.to_csv(DATA / f"{label}_fills.csv", index=False)
        r.holdings.to_parquet(DATA / f"{label}_holdings.parquet", index=False)
        r.open_positions.to_csv(HERE / f"{label}_open_positions.csv", index=False)
        r.rejected.to_csv(HERE / f"{label}_rejected.csv", index=False)
    contribution = (
        net.trades.groupby("symbol")
        .agg(
            closed_trades=("pnl", "size"),
            closed_pnl=("pnl", "sum"),
            gross_pnl=("gross", "sum"),
            costs=("costs", "sum"),
            win_rate=("pnl", lambda s: (s > 0).mean()),
        )
        .reindex([f"{a}/{c}" for a, c in PRIMARY])
        .fillna(0)
    )
    contribution["open_pnl"] = (
        net.open_positions.set_index("pair").pnl.reindex(contribution.index).fillna(0)
        if len(net.open_positions)
        else 0.0
    )
    contribution["total_pnl"] = contribution.closed_pnl + contribution.open_pnl
    contribution.reset_index().to_csv(HERE / "pair_contributions.csv", index=False)
    annual = monthly_returns(net.daily.equity)[["Year"]].rename(columns={"Year": "net"})
    annual["before_costs"] = monthly_returns(gross.daily.equity)["Year"]
    annual = annual.loc[net.daily.index[1].year :]
    annual.to_csv(HERE / "annual_returns.csv")
    ci = {period: block_interval(saved["Base net", period].daily.equity) for period in PERIODS}
    (HERE / "uncertainty.json").write_text(json.dumps(ci, indent=2) + "\n", encoding="utf-8")

    index = net.daily.index
    bench = b["signal"].loc[index]
    stocks = [s for p in PRIMARY for s in p]
    benchmark_curves = pd.DataFrame(
        {
            "SPY": bench.SPY / bench.SPY.iloc[0] * base.capital,
            "Six stocks buy and hold": (bench[stocks] / bench[stocks].iloc[0]).mean(axis=1)
            * base.capital,
        }
    )
    benchmark_curves.to_csv(DATA / "benchmarks.csv")
    benchmark_stats = pd.DataFrame(
        {k: equity_stats(v) for k, v in benchmark_curves.items()}
    ).T.reset_index(names="benchmark")
    benchmark_stats.to_csv(HERE / "benchmark_stats.csv", index=False)

    # Isolate direct cost drag using the net run's identical positions and dates.
    identical_gross = net.daily.equity + net.daily[COST_COLS].sum(axis=1).cumsum()
    identical_gross.rename("same_positions_before_costs").to_csv(DATA / "same_positions_gross.csv")

    # Independently rebuild NAV from leg fills. This frozen sample has no splits.
    q = net.fills.pivot_table(index="date", columns="symbol", values="quantity", aggfunc="sum")
    q = q.reindex(index).fillna(0).cumsum()
    previous_q = q.shift(1).fillna(0)
    price = b["close"].reindex(index)[q.columns]
    div = previous_q * b["dividend"].reindex(index)[q.columns]
    cash_changes = -(net.fills.quantity * net.fills.fill_price + net.fills.commission)
    cash_changes = cash_changes.groupby(net.fills.date).sum().reindex(index).fillna(0)
    borrow = -(previous_q * price.shift()).clip(upper=0).sum(axis=1)
    borrow *= base.borrow_rate * index.to_series().diff().dt.days.fillna(0) / 360
    cash_changes += div.sum(axis=1) - div.clip(lower=0).sum(axis=1) * base.withholding - borrow
    rebuilt = base.capital + cash_changes.cumsum() + (q * price).sum(axis=1)
    replay_error = float((rebuilt - net.daily.equity).abs().max())
    if replay_error > 1e-7:
        raise AssertionError(f"Independent fill replay failed: {replay_error}")

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.09,
        subplot_titles=(
            "Pairs strategy: $5,000 starting equity",
            "Net strategy drawdown",
            "Long-only context (different risk)",
        ),
    )
    for name, r, color in (("After costs", net, "#0072B2"), ("Before all costs", gross, "#009E73")):
        fig.add_trace(
            go.Scatter(x=index, y=r.daily.equity, name=name, line=dict(color=color)), row=1, col=1
        )
    fig.add_trace(
        go.Scatter(
            x=index,
            y=identical_gross,
            name="Same net positions, costs added back",
            line=dict(color="#898781", dash="dot"),
        ),
        row=1,
        col=1,
    )
    dd = net.daily.equity / net.daily.equity.cummax() - 1
    fig.add_trace(
        go.Scatter(x=index, y=dd, name="Drawdown", fill="tozeroy", line=dict(color="#D55E00")),
        row=2,
        col=1,
    )
    for name in benchmark_curves:
        fig.add_trace(go.Scatter(x=index, y=benchmark_curves[name], name=name), row=3, col=1)
    fig.update_layout(
        template="plotly_white",
        height=950,
        title="Competitor pairs | Jan 2017–Oct 9, 2026 | fixed rules",
    )
    fig.update_yaxes(tickformat=".0%", row=2, col=1)
    fig.write_html(DATA / "pairs_report.html", include_plotlyjs=True)

    caveats = [
        "Surviving pairs selected retrospectively; later periods are not pristine out-of-sample.",
        "Borrow availability/recalls unverified; 1% annual borrow and 5 bps fills assumed.",
        "30% long dividend withholding; full short dividend liability; ex-date accrual.",
        "Constant commission schedule; cash and short collateral yield zero.",
        "Stops trigger at close and execute next open; prices can gap beyond the threshold.",
        "Open positions marked at last close, without hypothetical terminal liquidation costs.",
        "Pair prices are synthetic units; side describes the first leg; see the leg fills table.",
    ]
    bundles = []
    for period in ("Full 2017-2026", "2026 YTD"):
        r = saved["Base net", period]
        path = publish_bundle(
            f"Competitor pairs net $5k {period}",
            r.daily.equity,
            r.trades,
            meta=dict(
                strategy="Competitor pairs: frozen 60-day spread mean reversion",
                params=asdict(base),
                costs={
                    k: getattr(base, k)
                    for k in ("plan", "slippage_bps", "borrow_rate", "withholding")
                },
                caveats=caveats,
                oos_start="2024-01-01",
                costs_description=(
                    "Costs include commissions/fees, slippage, short borrow, dividend withholding "
                    "and financing. Gross P&L precedes all five. Side means long/short the first "
                    "stock in the pair, with the opposite position in the second."
                ),
            ),
            benchmark=b["signal"].SPY.reindex(r.daily.index),
            tables={
                "holdings": r.holdings,
                "fills": r.fills,
                "daily": r.daily.reset_index(),
                "open_positions": r.open_positions,
            },
        )
        bundles.append(str(path.relative_to(ROOT)))

    audit = {
        "protocol_sha256": hashlib.sha256((HERE / "protocol.md").read_bytes()).hexdigest(),
        "data_manifest": manifest,
        "frozen_data_hashes_verified": True,
        "used_start": str(index[1].date()),
        "used_end": str(index[-1].date()),
        "whole_share_fills": bool(np.equal(net.fills.quantity, np.trunc(net.fills.quantity)).all()),
        "all_fills_after_signal": bool((net.fills.date > net.fills.signal_date).all()),
        "net_pnl_reconciliation_error": float(
            net.daily.equity.iloc[-1] - base.capital - contribution.total_pnl.sum()
        ),
        "financing_dollars": float(net.daily.financing.sum()),
        "independent_fill_replay_max_error": replay_error,
        "bundles": bundles,
    }
    (HERE / "verification.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    headline = summary[summary.variant.isin(["Base net", "Before all costs"])][
        ["variant", "period", "return", "cagr", "sharpe_zero_rf", "max_dd", "trades", "win_rate"]
    ]
    comparison = summary.pivot(index="variant", columns="period", values="return").reset_index()
    comparison = comparison.set_index("variant").reindex(variants).reset_index()
    contribution = contribution.reset_index()
    low, high = (
        ci["Full 2017-2026"]["annualized_mean_low"],
        ci["Full 2017-2026"]["annualized_mean_high"],
    )
    recent = summary[
        (summary.variant == "Base net") & summary.period.isin(["2024-2025", "2026 YTD"])
    ]
    passed = bool((recent["return"] > 0).all())
    verdict = "passes" if passed else "fails"
    contribution_table = table(
        contribution,
        pct=["win_rate"],
        dollars=["closed_pnl", "gross_pnl", "costs", "open_pnl", "total_pnl"],
    )
    report = f"""# Competitor pairs backtest

Frozen rules, named competitors, next-open fills. Sample: {index[1].date()} to {index[-1].date()}.
**The base strategy {verdict} the requirement of positive net returns in both
2024–2025 and 2026 YTD.** This is one specified strategy, not a test of every possible pairs model.

## Rules

KO/PEP, HD/LOW, MCD/YUM. Compute log relative total-return prices against the previous
60 closes, excluding today's observation. Enter at 2–4 standard deviations, long the
relatively cheap leg and short the rich leg. Freeze the entry mean/std. Exit after
crossing that mean, reaching 4 original standard deviations, or holding 40 sessions.
Every signal fills next open. Each pair has one third of account equity in gross
exposure, half per leg. Quantities are determined at the signal close, rounded down
to whole shares, and held constant. Reject dollar imbalance above 15% and entries
that exceed 1x gross at execution. Idle allocations stay in cash.

Base: $5,000, IBKR Tiered, 5 bps per fill, 1% annual short borrow (calendar/360),
30% withholding on long dividends, full short dividend liability. Cash earns zero.
Longs are funded from equity; short proceeds do not fund longs. Exceptional debit
balances cost an assumed 8% annually: **${net.daily.financing.sum():.2f} charged** in the base run.
Whole-share sizing and skip rules apply to the cost-free comparison too.

## Results

{table(headline, pct=["return", "cagr", "max_dd", "win_rate"])}

Sharpe uses a zero risk-free rate and all trading sessions, including flat days.
The 2026 return is YTD; its CAGR column mechanically annualizes a partial year.
Each subperiod restarts flat at $5,000 with earlier observations used for warm-up.
Consequently these subperiod returns need not chain into the continuous full run.
Full-period ending equity: **${net.daily.equity.iloc[-1]:,.2f}**.

## Pair contributions to the uninterrupted base portfolio

{contribution_table}

Pair P&L includes any final open mark. Win rates are for closed round trips only.
Full-period modeled costs: {", ".join(f"{k} ${net.daily[k].sum():,.2f}" for k in COST_COLS)}.
Gross and net paths size independently as equity changes, so their NAV difference
is not simply the sum of net-run costs. Average gross exposure was
{net.daily.gross.iloc[1:].mean():.1%}; maximum was {net.daily.gross.max():.1%}.
Holding the net run's exact quantities and dates fixed, adding back modeled costs
produces ending equity of **${identical_gross.iloc[-1]:,.2f}**. Direct cost drag is
${net.daily[COST_COLS].sum().sum():,.2f}; the remaining difference from the independent
cost-free run comes from sizing and which entries were accepted. Lower costs need
not monotonically improve a rounded-share path when the trades themselves change.

## Predeclared sensitivity checks

Values below are cumulative period returns, **not annualized**. Each row changes
one assumption except the explicitly cost-free and expanded-universe diagnostics.
The baseline was not replaced by the best-looking row.

{table(comparison, pct=list(PERIODS))}

The single-pair rows allocate the whole account's 1x gross limit to that pair;
they therefore differ from its one-third allocation in the contribution table.
The $100k row also assumes zero cash/short-collateral interest, understating the
cash yield potentially available at that account size.

## Year-by-year, uninterrupted portfolio

{table(annual.reset_index(), pct=["net", "before_costs"])}

## Uncertainty and limitations

A circular 20-session block bootstrap (2,000 draws, fixed seed) gives a 95%
interval of **{low:+.2%} to {high:+.2%}** for the base strategy's annualized mean
daily return. This is not a prediction interval or an independent validation;
few pairs, serial dependence, regime changes and retrospective selection remain.

{" ".join(caveats[:-1])}
The 2024+ dashboard split is chronological only. No valuation-multiple, earnings,
cointegration, or sector-neutrality claim is made. Similar products do not guarantee
economic convergence. Liquidity, exact auction execution, locate availability,
payment-date dividend timing and historical broker house margin were not reconstructed.
Recorded dividends and splits are handled explicitly; data come from a prototype
vendor rather than an audited point-in-time institutional feed.

## Long-only context

{table(benchmark_stats[["benchmark", "CAGR", "Sharpe", "max DD"]], pct=["CAGR", "max DD"])}

These benchmarks use fractional total-return buy-and-hold before costs and taxes;
the six stocks are equally weighted at inception, not rebalanced daily. They carry
market exposure and have much higher invested capital than the pairs strategy.

## Artifacts and reproduction

- [Protocol](protocol.md), [settings](settings.json), [summary CSV](summary.csv),
  [verification](verification.json), [pair trades](net_trades.csv).
- Standalone interactive chart: `data/pairs_2026_10_12/pairs_report.html`.
- Daily ledger, exact leg fills and holdings: `data/pairs_2026_10_12/`.
- Dashboard bundles: {", ".join(f"`{p}`" for p in bundles)}.
- Run `.venv\\Scripts\\python.exe research/pairs_2026_10_12/run.py` against the
  frozen raw files; hashes are recorded in verification.json.
- Tests: `.venv\\Scripts\\python.exe -m pytest tests/test_pairs.py -q`.

Sources and motivation: [Gatev et al.](https://doi.org/10.1093/rfs/hhj020),
[Villota 2025](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5141328),
[IBKR commissions](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php),
[short-sale costs](https://www.interactivebrokers.com/en/pricing/short-sale-cost.php).
"""
    (HERE / "report.md").write_text(report, encoding="utf-8")
    (ROOT / "research/pairs_trading.md").write_text(
        "# Competitor pairs: fixed-rule backtest\n\n"
        + f"2017–2026-10-09, $5,000: {equity_stats(net.daily.equity)['CAGR']:+.2%} CAGR "
        + f"net, Sharpe {equity_stats(net.daily.equity)['Sharpe']:.2f}. "
        + "KO/PEP, HD/LOW and MCD/YUM, next-open execution and explicit carry costs.\n\n"
        + "[Full report](pairs_2026_10_12/report.md) · "
        + "[Protocol](pairs_2026_10_12/protocol.md)\n",
        encoding="utf-8",
    )
    write_manifest(
        HERE / "result.json",
        id="research:competitor-pairs-2026-10-12",
        name="Competitor pairs: 2017–2026 backtest",
        kind="research",
        description="Competitor pairs with next-open whole-share fills and carry costs",
        start=str(index[1].date()),
        end=str(index[-1].date()),
        include=[
            "*.xml",
            "*.md",
            "*.csv",
            "*.json",
            "data:pairs_2026_10_12/*.csv",
            "data:pairs_2026_10_12/*.html",
        ],
    )
    print(headline.to_string(index=False), flush=True)
    print(f"Report: {HERE / 'report.md'}", flush=True)


if __name__ == "__main__":
    main()
