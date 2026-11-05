"""Verify saved account cash paths and build an offline capital-comparison report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from horizon_trader.backtest.research_stats import risk_free
from horizon_trader.config import data_dir
from horizon_trader.execution.costs import IBKR_PLANS

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
OUT = HERE / "results"
DATA = data_dir() / "shared_account_2026_10_01"
SIZES = (5000, 10000, 15000, 20000)


def markdown(frame):
    # No optional tabulate dependency.
    return (
        "| "
        + " | ".join(frame.columns)
        + " |\n| "
        + " | ".join("---" for _ in frame)
        + " |\n"
        + "\n".join(
            "| " + " | ".join(str(x) for x in row) + " |"
            for row in frame.itertuples(index=False, name=None)
        )
    )


def verify():
    hashes = {}
    for stage in ("main", "stress", "older"):
        manifest = json.loads((OUT / f"{stage}_manifest.json").read_text())
        if manifest["quick"] or manifest["sizes"] != list(SIZES):
            raise ValueError("Incomplete four-capital run")
        for name, expected in manifest["source_hashes"].items():
            if name in hashes and hashes[name] != expected:
                raise ValueError(f"Input/code changed between stages: {name}")
            hashes[name] = expected
    for name, expected in hashes.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Changed input/code: {name}")
    raw = {p.stem: pd.read_parquet(p) for p in (DATA / "raw").glob("*.parquet")}
    rows = []
    for folder in sorted((DATA / "runs").iterdir()):
        if folder.name.endswith("_quick"):
            continue
        daily = pd.read_parquet(folder / "daily.parquet")
        orders = pd.read_parquet(folder / "orders.parquet")
        flows = pd.read_parquet(folder / "flows.parquet")
        movement = pd.Series(0.0, index=daily.index)
        quantities = pd.DataFrame(index=daily.index)
        if len(orders):
            if not np.isclose(orders.quantity, orders.quantity.round()).all():
                raise ValueError("Fractional trade")
            if not (orders.price > 0).all() or not (orders.fee >= 0).all():
                raise ValueError("Invalid execution")
            trades = orders.assign(
                date=pd.to_datetime(orders.time).dt.normalize(),
                change=-orders.quantity * orders.price - orders.fee,
            )
            movement += trades.groupby("date").change.sum().reindex(daily.index, fill_value=0)
            quantities = (
                trades.pivot_table(index="date", columns="symbol", values="quantity", aggfunc="sum")
                .reindex(daily.index)
                .fillna(0.0)
            )
            model = IBKR_PLANS["tiered" if "_tiered_" in folder.name else "fixed"]
            if "no_minimum_diagnostic" in folder.name:
                from dataclasses import replace

                model = replace(model, min_per_order=0.0)
            expected = np.array([model.total(r.quantity, r.price) for r in orders.itertuples()])
            if not np.allclose(orders.fee, expected, atol=1e-10):
                raise ValueError("Fees do not match executed net orders")
        receivable = pd.Series(0.0, index=daily.index)
        if len(flows):
            cash = flows[flows.kind.ne("dividend_receivable")].copy()
            cash["date"] = pd.to_datetime(cash.date)
            movement += cash.groupby("date").amount.sum().reindex(daily.index, fill_value=0)
            for kind, sign in (("dividend_receivable", 1), ("dividend_payment", -1)):
                selected = flows[flows.kind.eq(kind)].copy()
                selected["date"] = pd.to_datetime(selected.date)
                receivable += sign * selected.groupby("date").amount.sum().reindex(
                    daily.index, fill_value=0
                )
        receivable = receivable.cumsum()
        holdings_value = pd.Series(0.0, index=daily.index)
        for symbol in quantities:
            if symbol not in raw:
                if quantities[symbol].cumsum().abs().max() > 1e-8:
                    raise ValueError(f"Intraday stock held overnight: {symbol}")
                continue
            source = raw[symbol]
            splits = source["Stock Splits"].replace(0.0, 1.0)
            growth = splits.reindex(daily.index).cumprod()
            shares = quantities[symbol].div(growth).cumsum().mul(growth)
            future_splits = splits.iloc[::-1].cumprod().iloc[::-1].div(splits)
            price = source.Close.mul(future_splits).reindex(daily.index)
            holdings_value += shares * price
        nav_error = (daily.cash + holdings_value + receivable - daily.equity).abs().max()
        receivable_error = (receivable - daily.receivables).abs().max()
        if max(nav_error, receivable_error) > 1e-7:
            raise ValueError(f"Independent position/NAV reconstruction failed: {folder.name}")
        error = (daily.cash.diff().fillna(0) - movement).abs().max()
        if error > 1e-7 or not np.isfinite(daily.equity).all() or (daily.equity <= 0).any():
            raise ValueError(f"Cash path failed for {folder.name}: {error}")
        rows.append(
            dict(
                run=folder.name,
                cash_identity_error=error,
                nav_identity_error=nav_error,
                receivable_error=receivable_error,
                orders=len(orders),
                sessions=len(daily) - 1,
            )
        )
    pd.DataFrame(rows).to_csv(OUT / "account_verification.csv", index=False)
    result = dict(
        verified_runs=len(rows),
        source_hashes=len(hashes),
        max_cash_identity_error=max(r["cash_identity_error"] for r in rows),
        max_nav_identity_error=max(r["nav_identity_error"] for r in rows),
        checks=[
            "cash changes = net trades + paid dividends - funding - short fees",
            "integer orders",
            "NAV independently reconstructed from net orders, splits, raw closes and receivables",
            "positive finite NAV",
            "per-order fee recomputation",
            "source input/code hashes",
            "all four requested capital sizes",
        ],
    )
    (OUT / "verification.json").write_text(json.dumps(result, indent=2))
    return result


def charts():
    figure = make_subplots(rows=2, cols=2, subplot_titles=[f"${c:,} start" for c in SIZES])
    drawdowns = make_subplots(rows=2, cols=2, subplot_titles=[f"${c:,} start" for c in SIZES])
    colors = {
        "frozen": "#3366cc",
        "reduced": "#dc3912",
        "core": "#109618",
        "qqq_buy_hold": "#444444",
    }
    curve_rows = []
    labels = {"frozen": "Frozen allocation", "reduced": "Daily + reduced intraday",
              "core": "Daily core", "qqq_buy_hold": "QQQ (whole shares)"}
    for i, capital in enumerate(SIZES):
        for strategy, color in colors.items():
            folder = DATA / "runs" / f"continuous_base_{strategy}_{capital}"
            daily = pd.read_parquet(folder / "daily.parquet")
            figure.add_trace(
                go.Scatter(
                    x=daily.index,
                    y=daily.equity,
                    name=labels[strategy],
                    legendgroup=strategy,
                    showlegend=i == 0,
                    line=dict(color=color),
                ),
                row=i // 2 + 1,
                col=i % 2 + 1,
            )
            curve_rows.append(daily[["equity"]].assign(capital=capital, strategy=strategy))
            drawdowns.add_trace(go.Scatter(x=daily.index,
                y=daily.equity / daily.equity.cummax() - 1, name=labels[strategy],
                legendgroup=strategy, showlegend=i==0, line=dict(color=color)),
                row=i//2+1, col=i%2+1)
    figure.update_layout(
        title="One account, whole shares, Fixed fees — 2x gross model",
        template="plotly_white",
        height=900,
        hovermode="x unified",
    )
    figure.write_html(HERE / "capital_comparison.html", include_plotlyjs=True)
    drawdowns.update_layout(title="Daily closing drawdowns", template="plotly_white",
                            height=850, hovermode="x unified")
    drawdowns.update_yaxes(tickformat=".0%")
    page = HERE / "capital_comparison.html"
    content = page.read_text(encoding="utf-8")
    chart = drawdowns.to_html(include_plotlyjs=False, full_html=False)
    content = content.replace("</body>", chart + "</body>")
    page.write_text(content, encoding="utf-8")
    pd.concat(curve_rows).to_csv(OUT / "plot_equity.csv")


def uncertainty():
    rates = pd.read_parquet(data_dir() / "research_cycle_2026_10_01/inputs/dff.parquet").ff
    rng = np.random.default_rng(20261001)
    rows = []
    for capital in SIZES:
        daily = {
            name: pd.read_parquet(
                DATA / "runs" / f"continuous_base_{name}_{capital}" / "daily.parquet"
            ).equity
            for name in ("core", "frozen", "reduced")
        }
        returns = pd.DataFrame({name: eq.pct_change() for name, eq in daily.items()}).loc[
            "2024-01-01":
        ]
        rf = risk_free(daily["core"].index, rates).reindex(returns.index)
        values = returns.sub(rf, axis=0).to_numpy()
        n = len(values)
        ix = (rng.integers(n, size=(1000, int(np.ceil(n / 21)), 1)) + np.arange(21)) % n
        samples = values[ix.reshape(1000, -1)[:, :n]]
        sharpes = samples.mean(axis=1) / samples.std(axis=1, ddof=1) * np.sqrt(252)
        observed = values.mean(axis=0) / values.std(axis=0, ddof=1) * np.sqrt(252)
        for j, name in enumerate(("core", "frozen", "reduced")):
            if j:
                low, high = np.quantile(sharpes[:, j] - sharpes[:, 0], [0.025, 0.975])
                rows.append(
                    dict(
                        capital=capital,
                        strategy=name,
                        period="reused_2024_plus",
                        incremental_sharpe=observed[j] - observed[0],
                        ci95_low=low,
                        ci95_high=high,
                        samples=1000,
                        block_sessions=21,
                        multiple_testing_adjusted=False,
                    )
                )
    pd.DataFrame(rows).to_csv(OUT / "uncertainty.csv", index=False)


def main():
    verification = verify()
    tables = {
        stage: pd.read_csv(OUT / f"{stage}_metrics.csv") for stage in ("main", "stress", "older")
    }
    all_rows = pd.concat(tables.values(), ignore_index=True)
    all_rows.to_csv(OUT / "experiment_ledger.csv", index=False)
    full = tables["main"].query("restart == 'continuous' and period == 'full'")
    primary = full[full.strategy.isin(["frozen", "reduced"])].copy()
    formatted = pd.DataFrame(
        {
            "Account": primary.capital.map("${:,.0f}".format),
            "Allocation": primary.strategy,
            "Net CAGR": primary.cagr.map("{:.2%}".format),
            "Max DD": primary.max_drawdown.map("{:.2%}".format),
            "Excess Sharpe": primary.sharpe.map("{:.2f}".format),
            "End NAV": primary.final_equity.map("${:,.0f}".format),
            "Fees": primary.fees.map("${:,.0f}".format),
            "Cap-breach days": primary.breach_days.astype(int),
        }
    )
    stress = tables["stress"].query("period == 'full'")
    stress_pivot = stress.pivot(index=["scenario", "strategy"], columns="capital", values="cagr")
    stress_display = stress_pivot.map(lambda v: f"{v:.2%}").reset_index()
    stress_display.columns = [str(c) for c in stress_display.columns]
    restart = tables["main"].query("restart == 'restart_2024' and period == 'full'")
    restart = restart[restart.strategy.isin(["frozen", "reduced"])].copy()
    restart_table = pd.DataFrame(
        {
            "Account": restart.capital.map("${:,.0f}".format),
            "Allocation": restart.strategy,
            "CAGR": restart.cagr.map("{:.2%}".format),
            "Max DD": restart.max_drawdown.map("{:.2%}".format),
            "End NAV": restart.final_equity.map("${:,.0f}".format),
        }
    )
    older = tables["older"].query("period == 'older_full'").copy()
    older_table = pd.DataFrame(
        {
            "Account": older.capital.map("${:,.0f}".format),
            "Control": older.strategy,
            "CAGR": older.cagr.map("{:.2%}".format),
            "Max DD": older.max_drawdown.map("{:.2%}".format),
        }
    )
    observations = []
    for path in (data_dir() / "live/observations").glob("*.jsonl"):
        observations += [json.loads(line) for line in path.read_text().splitlines()]
    kinds = pd.Series([r["kind"] for r in observations]).value_counts().to_dict()
    quotes = [r for r in observations if r["kind"] == "quote"]
    usable = sum(r.get("valid_two_sided", False) and r.get("market_data_type") == 1 for r in quotes)
    observation_summary = dict(
        event_counts=kinds,
        valid_two_sided_live_type_rows=usable,
        note="Counts include repeated observations, not unique fills; current-day snapshots only",
    )
    (OUT / "observation_status.json").write_text(json.dumps(observation_summary, indent=2))
    charts()
    uncertainty()
    qqq = full.iloc[0]
    text = f"""# Shared-account results at $5k, $10k, $15k and $20k

The prior return-stream combination overstated small-account feasibility.
Actual minimum commissions, whole shares and shared buying power materially
change the result. **No allocation is established as meeting the original objective
across the required periods and adverse conditions.** These are conditional
historical account simulations, not broker-certified execution or live results.

Initial NAV 2021-11-01; first trade 2021-11-02; final mark 2026-09-24.
QQQ gross total return on the same first-open/end-close dates: **{qqq.qqq_cagr:.2%}
CAGR / {qqq.qqq_max_drawdown:.2%} maximum drawdown**. QQQ has no subscription,
transaction, withholding or financing costs; executable whole-share QQQ is a
separate saved control. Strategy figures exclude research/data subscription bills.

## Four account sizes

Frozen: 51.60% daily core / 20.33% ORB / 28.07% QQQ noise sleeve budgets.
Reduced: 100% daily core plus 25% ORB and 50% noise sleeve budgets; the intraday
strategies themselves request leverage. These weights remain unchanged at every size.

{markdown(formatted)}

Every fee minimum is charged to an executed, netted order. Positions in the same
ticker share one cash balance and one gross limit. ORB candidate orders reserve
buying power even on days they never fill. Same-time QQQ reversals are one net
order. Daily sizing uses prior-close information, with 1% reserve and resizing
after opening gaps; it is an approximate opening-session execution model.

Cap-breach days mean minute marks or closing inventory crossed the **model's**
gross limit after prices moved. They do not establish a historical IBKR margin
call. Such paths fail acceptance here; forced liquidation prices are not modeled.
The base intraday cap is 2x and the daily core's overnight cap 1x. The QQQ
volatility control has its declared 1.5x target / 2x drift limit. The account's
actual jurisdiction, house margin and small-balance restrictions remain unverified.

## Fresh 2024 account restarts

Each account starts anew at its stated size on 2023-12-29, first fill 2024-01-02.
This separates current small-balance execution from accounts grown since 2021.

{markdown(restart_table)}

## Costs, latency and restrictions

Full-period net CAGR below; every trial, including failures, is retained in the
[experiment ledger](results/experiment_ledger.csv). The no-minimum case is a
diagnostic added to explain fee sensitivity, not an available broker offering.
The 4x scenario is hypothetical. Long-only here means no **net account shorts**;
a short signal can first sell an existing daily long holding.

{markdown(stress_display)}

Latency replays the same ORB candidate with later order placement, requires a
trigger and later-minute trade-through, then computes a new stop path. Noise
signals fill one/five minutes later. Higher-cost cases add 1c on all intraday fills,
including auction exits, and use 10bp for daily fills. Joint stress also adds one
daily-session delay, 1x/no-net-shorts, deterministic missed ORB entries and 30%
dividend withholding. Borrow is an assumed 3% annualized on the day's peak net
short value, charged for a full day; no historical locate availability is implied.
Paired 21-session block-bootstrap intervals for incremental Sharpe are saved in
[uncertainty.csv](results/uncertainty.csv). They do not correct prior strategy selection.

## Older-regime validation

Existing-subscription checks returned **HTTP 403** for 2017-01-03 and 2020-03-16
minute files. No purchase or subscription change occurred. The following extension
uses existing daily ETF histories, 2007-01-03 initial NAV through 2021-10-01.
It covers daily controls only; older ORB/noise/combined validation remains unfinished
pending data access. Financial crisis, pre-COVID and COVID subperiods are saved.

{markdown(older_table)}

## Forward observations

The read-only observer successfully connected to the paper Gateway. Recorded
event counts: `{json.dumps(kinds, sort_keys=True)}`. Valid two-sided live-type quote
rows: **{usable}**. Actual recorded broker execution events/snapshots:
**{kinds.get("execution", 0) + kinds.get("execution_snapshot", 0)}**
(may include duplicate snapshot/event records). It does not submit orders.

Windows task `horizon-trader observations` is registered for weekdays at 09:24 ET,
refreshes recent Massive history and observes until 16:05 ET. Gateway must remain
logged into paper and the PC available. Scanner and ORB intent logs include all
four starting sizes. These are unsubmitted candidate intents, not funded forward
portfolio returns. Commission/execution events are captured if paper orders are
placed through the existing adapter or manually; none were placed by this work.
The first check received IBKR error 354 for every ETF; live-to-paper sharing is
being configured. Subscription errors, delayed types and missing quotes remain
explicit in logs. [IBKR sharing instructions](https://www.ibkrguides.com/clientportal/papertradingaccount.htm).

## Reproducibility and limitations

Verification: **{verification["verified_runs"]} account paths**, {verification["source_hashes"]}
source hashes; maximum independent daily-cash reconstruction error
{verification["max_cash_identity_error"]:.3g} dollars. Whole-share orders, finite NAV
and per-order fee amounts checked. The full repository test result is recorded in
the final verification note. Protocol, raw actions, prices and signals are frozen;
large/private artifacts stay in `data/shared_account_2026_10_01/` (git-ignored).
Preserve that directory along with the report for exact replay.

This model still uses inherited ORB fill assumptions without quote/queue history,
minute-resolution rather than tick-level margin, gross-dividend baseline, zero
cash interest, a dividend-payment proxy where vendor dates are absent, approximate
opening executions and uniform historical fee schedules. No historical short
availability or account restrictions were invented. Reused history is not an
untouched holdout. The existing live strategies/settings were not changed.

[Offline capital curves](capital_comparison.html),
[account checks](results/account_verification.csv),
[implementation decisions](implementation_notes.md), [frozen protocol](protocol.md).

```powershell
.venv/Scripts/python.exe research/shared_account/prepare.py raw
.venv/Scripts/python.exe research/shared_account/prepare.py dividends
.venv/Scripts/python.exe research/shared_account/prepare.py minutes
.venv/Scripts/python.exe research/shared_account/replay.py --stage main
.venv/Scripts/python.exe research/shared_account/replay.py --stage stress
.venv/Scripts/python.exe research/shared_account/replay.py --stage older
.venv/Scripts/python.exe research/shared_account/report.py
```
"""
    (HERE / "report.md").write_text(text, encoding="utf-8")
    print(json.dumps(verification, indent=2))
    print(formatted.to_string(index=False))


if __name__ == "__main__":
    main()
