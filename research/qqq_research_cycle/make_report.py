"""Build the report, complete ledger, and offline Plotly curves from saved results.

    .venv/Scripts/python.exe research/qqq_research_cycle/make_report.py

No backtests, downloads, or strategy selection occur here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import yaml
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "results"
CONFIG = ROOT / "config/experiments/research_cycle_2026_10_01.yaml"


def markdown(frame: pd.DataFrame) -> str:
    """No optional tabulate dependency required."""
    return "\n".join(
        [
            "| " + " | ".join(map(str, frame.columns)) + " |",
            "| " + " | ".join(["---"] * len(frame.columns)) + " |",
            *[
                "| " + " | ".join(map(str, row)) + " |"
                for row in frame.itertuples(index=False, name=None)
            ],
        ]
    )


def display(frame, columns):
    out = frame[list(columns)].copy()
    percentages = {
        "cagr",
        "max_drawdown",
        "mean_exposure",
        "dd_reduction",
        "alpha_annual",
        "annual_log_growth_gap",
        "ci95_low",
        "ci95_high",
        "mean_qqq_exposure",
    }
    for col in out:
        if col in percentages:
            out[col] = out[col].map(lambda x: f"{x:.2%}")
        elif col in {"sharpe", "sortino", "beta_qqq", "turnover_annual", "max_exposure"}:
            out[col] = out[col].map(lambda x: f"{x:.2f}")
        elif col in {"fees", "borrow_cost", "slippage"}:
            out[col] = out[col].map(lambda x: f"${x:,.0f}")
        elif col == "familywise_one_sided_p":
            out[col] = out[col].map(lambda x: f"{x:.3f}")
    return markdown(out.rename(columns=columns))


def curves(selected):
    eq = pd.read_csv(OUT / "full_equity.csv", index_col="date", parse_dates=True)
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=(
            "Net equity — $5,000 initial capital (log scale)",
            "Drawdown from prior peak",
        ),
    )
    names = [
        "qqq_total_return",
        selected,
        "trend_200",
        "qqq_vol_only",
        "voltrend_20",
        "equal_weight",
    ]
    colors = ["#111827", "#d97706", "#16a34a", "#2563eb", "#9333ea", "#64748b"]
    for name, color in zip(names, colors, strict=True):
        visible = "legendonly" if name in {"voltrend_20", "equal_weight"} else True
        for row, values in [(1, eq[name]), (2, eq[name] / eq[name].cummax() - 1)]:
            fig.add_trace(
                go.Scatter(
                    x=eq.index,
                    y=values,
                    name=name,
                    legendgroup=name,
                    showlegend=row == 1,
                    visible=visible,
                    line={"color": color, "width": 1.5},
                    hovertemplate="%{x|%Y-%m-%d}: %{y:.3f}<extra>%{fullData.name}</extra>",
                ),
                row=row,
                col=1,
            )
    for date in ["2016-01-01", "2021-01-01"]:
        fig.add_vline(x=date, line_dash="dash", line_color="#94a3b8")
    for x, text in [
        ("2011-01-01", "Development"),
        ("2018-01-01", "Validation"),
        ("2024-01-01", "Historical confirmation — reused"),
    ]:
        fig.add_annotation(x=x, y=1.06, xref="x", yref="paper", text=text, showarrow=False)
    fig.update_yaxes(type="log", row=1, col=1)
    fig.update_yaxes(tickformat=".0%", row=2, col=1)
    fig.update_layout(
        template="plotly_white",
        height=850,
        title="QQQ research cycle: no candidate meets both targets",
        hovermode="x unified",
        legend={"orientation": "h", "y": -0.1},
        margin={"t": 110},
    )
    fig.write_html(OUT / "curves.html", include_plotlyjs=True, full_html=True)


def ledger(config, table):
    blocks = [table.assign(scenario="base", evaluation="continuous_account")]
    for file, label in [
        ("stress_metrics.csv", "stress"),
        ("restart_metrics.csv", "restart"),
        ("dotcom_metrics.csv", "dotcom"),
        ("walk_forward_metrics.csv", "walk_forward"),
    ]:
        t = pd.read_csv(OUT / file)
        if "scenario" not in t:
            t["scenario"] = label
        blocks.append(t.assign(evaluation=label))
    combined = pd.concat(blocks, ignore_index=True)
    specs = {s["name"]: s for s in config["variants"] + config["controls"]}
    combined["parameters"] = combined.strategy.map(
        lambda n: json.dumps(specs.get(n, {}), sort_keys=True)
    )
    combined["role"] = combined.strategy.map(
        lambda n: (
            "candidate" if n in {s["name"] for s in config["variants"]} else "control_or_selector"
        )
    )

    def rejection(row):
        reasons = []
        if row.cagr_gap <= 0:
            reasons.append("CAGR does not exceed QQQ")
        if row.dd_reduction < 0.10:
            reasons.append("drawdown reduction below 10%")
        if row.margin_breach_days:
            reasons.append("margin breach")
        return (
            "; ".join(reasons)
            or "descriptive period pass; requires all acceptance periods and stresses"
        )

    combined["outcome_reason"] = combined.apply(rejection, axis=1)
    combined.to_csv(OUT / "experiment_ledger.csv", index=False)
    return combined


def main():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    selection = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))
    selected = selection["selected"]
    table = pd.read_csv(OUT / "metrics.csv")
    stress = pd.read_csv(OUT / "stress_metrics.csv")
    uncertainty = pd.read_csv(OUT / "uncertainty.csv")
    restarts = pd.read_csv(OUT / "restart_metrics.csv")
    wf = pd.read_csv(OUT / "walk_forward_metrics.csv")
    dotcom = pd.read_csv(OUT / "dotcom_metrics.csv")
    recorded = ledger(config, table)
    curves(selected)
    # Calendar-year total returns (2026 is YTD), separate from annualized CAGR.
    eq = pd.read_csv(OUT / "full_equity.csv", index_col="date", parse_dates=True)
    eq.resample("YE").last().pct_change().iloc[1:].to_csv(OUT / "calendar_year_returns.csv")
    names = [
        "qqq_total_return",
        "qqq_buy_hold",
        "trend_200",
        "voltrend_20",
        "voltrend_25",
        selected,
        "rotation_252",
        "qqq_vol_only",
        "qqq_125",
        "equal_weight",
    ]
    full = table[table.period == "full"].set_index("strategy").loc[names].reset_index()
    headline = display(
        full,
        {
            "strategy": "Strategy",
            "cagr": "Net CAGR",
            "max_drawdown": "Max DD",
            "drawdown_days": "DD days",
            "sharpe": "Sharpe",
            "sortino": "Sortino",
            "mean_exposure": "Mean gross",
            "turnover_annual": "Turnover/yr",
            "orders": "Orders",
        },
    )
    splits = display(
        table[
            table.period.isin(["development", "validation", "confirmation_reused"])
            & table.strategy.isin(
                ["qqq_total_return", selected, "trend_200", "voltrend_20", "qqq_vol_only"]
            )
        ],
        {
            "period": "Period",
            "strategy": "Strategy",
            "cagr": "CAGR",
            "max_drawdown": "Max DD",
            "objective_pass": "Both targets",
        },
    )
    neighborhood = display(
        table[
            (table.period == "full") & table.strategy.isin([s["name"] for s in config["variants"]])
        ],
        {
            "strategy": "Variant",
            "cagr": "CAGR",
            "max_drawdown": "Max DD",
            "dd_reduction": "DD reduction",
            "objective_pass": "Both targets",
        },
    )
    sensitivities = display(
        stress[(stress.period == "full") & stress.strategy.isin([selected, "qqq_vol_only"])],
        {
            "scenario": "Scenario",
            "strategy": "Strategy",
            "cagr": "CAGR",
            "max_drawdown": "Max DD",
            "objective_pass": "Both targets",
        },
    )
    comparison = display(
        table[
            (table.period == "full")
            & table.strategy.isin(
                [
                    selected,
                    "matched_rotation_126",
                    "trend_200",
                    "matched_trend_200",
                    "voltrend_20",
                    "matched_voltrend_20",
                    "qqq_vol_only",
                    "qqq_125",
                    "equal_weight",
                ]
            )
        ],
        {
            "strategy": "Strategy",
            "cagr": "CAGR",
            "max_drawdown": "Max DD",
            "mean_exposure": "Mean gross",
            "beta_qqq": "QQQ beta",
            "alpha_annual": "OLS alpha/yr",
        },
    )
    costs = display(
        full,
        {
            "strategy": "Strategy",
            "fees": "Fees",
            "slippage": "Slippage",
            "borrow_cost": "Funding",
            "max_exposure": "Max gross",
            "cash_clipped": "Resized purchases",
        },
    )
    uncertain = display(
        uncertainty,
        {
            "strategy": "Variant",
            "annual_log_growth_gap": "Log growth gap/yr",
            "ci95_low": "95% low",
            "ci95_high": "95% high",
            "familywise_one_sided_p": "Familywise p",
        },
    )
    restart_table = display(
        restarts[restarts.strategy.isin([selected, "qqq_vol_only", "qqq_total_return"])],
        {
            "period": "Fresh $5k account",
            "strategy": "Strategy",
            "cagr": "CAGR",
            "max_drawdown": "Max DD",
        },
    )
    wf_table = display(wf, {"strategy": "Strategy", "cagr": "CAGR", "max_drawdown": "Max DD"})
    dotcom_table = display(
        dotcom[
            dotcom.strategy.isin(["trend_200", "voltrend_20", "qqq_vol_only", "qqq_total_return"])
        ],
        {
            "strategy": "Strategy",
            "cagr": "CAGR",
            "max_drawdown": "Max DD",
        },
    )
    regimes = display(
        table[
            table.period.isin(
                [
                    "financial_crisis",
                    "recovery",
                    "pre_covid",
                    "covid",
                    "2021",
                    "inflation_2022",
                    "recent",
                ]
            )
            & table.strategy.isin([selected, "qqq_vol_only", "qqq_total_return"])
        ],
        {
            "period": "Regime",
            "strategy": "Strategy",
            "cagr": "CAGR",
            "max_drawdown": "Max DD",
        },
    )
    text = f"""# QQQ research cycle — 2026-10-01

**No candidate meets the objective.** Across 2007–2026-09-30, QQQ total return
compounds at 16.34% with a 53.40% maximum drawdown. All nine new candidate variants
reduce drawdown by more than the required 10% relative amount over the full period,
but all sacrifice return. None passes both targets in 2016–2020 validation or the
2021+ historical confirmation. The development-selected six-month rotation is
rejected: 11.12% net CAGR and 35.96% drawdown, versus QQQ's 16.34% and 53.40%.

The most informative control is **volatility-only QQQ**: 16.22% net CAGR and 38.70%
drawdown (27.5% smaller), a near match in growth, not a win. Its 2021+ period passes
both targets, but validation does not. Adding the trend gate lowers full-period
growth to 11.95%. Constant 1.25x QQQ raises CAGR to 19.03% while worsening drawdown
to 63.02%; that is leverage, not the requested improvement.

Recommendation: **reject the selected rotation for this objective; continue narrowly
scoped risk-sizing research. Do not promote a strategy to paper trading on this
cycle's performance evidence.** No orders or live-setting changes were made.

## Current system and data assessment

The repository combines close-time target-weight ETF sleeves (momentum, trend,
volatility management, mean reversion), portfolio caps, and next-open execution.
It also contains ORB, intraday momentum, point-in-time stock/fundamental research,
social and disclosure event studies, and broker/shadow infrastructure. Relevant
existing research was read; unrelated application code was not exhaustively audited.

The existing Tiered/5bp/$5k daily baseline reproduces for 2008-01-02–2026-09-30:
combined 6.4% CAGR / -11.5% DD, QQQ 16.4% / -49.4%. These legacy results use different
start dates and execution conventions from the new table and must not be mixed.
See [simulator audit](legacy_audit.md) and [data audit](data_audit.md).

Two defects were fixed with regression tests: the legacy simulator invented fills
at stale prior closes when opens were absent/invalid; its analytics Sortino used
conditional negative-return standard deviation instead of downside RMS. Complete
ETF-panel baseline results were unaffected by the missing-open fix. Remaining
legacy issues include adjusted-unit share fees, exact-open sizing, fractional
orders, and uncharged small negative cash. A research-only account now explicitly
handles these matters; live modules/settings were not repurposed.

Frozen QQQ/GLD/IEF data are complete on common sessions, with no missing/duplicate
prices or OHLC violations in the audited cache. QQQ starts 1999-03-10, GLD
2004-11-18, IEF 2002-07-30. Raw price/dividend/split data were separately retrieved
without changing existing caches. Raw dividend reconstruction agrees with QQQ's
adjusted total return to 0.00343% of terminal wealth over 2007+ (maximum one-day
difference 0.71 bp). This supports a gross-dividend-reinvested benchmark; it is not
independent institutional-grade vendor validation. Yahoo history can be revised.

The 2021+ intraday sample contains many prior experiments, including a 480-config
ORB search. At least 89 previous result bundles and research documents already
use the recent history. **There is no credible untouched holdout.** The four fresh
late-September sessions are insufficient. The ETF set avoids today's surviving
stock constituent list, but asset/hypothesis choice still reflects observed history.

## Frozen protocol and interpretation

The [protocol](protocol.md) and
[configuration](../../config/experiments/research_cycle_2026_10_01.yaml)
precede candidate calculations. Ranked hypotheses, mechanisms and falsifiers are
recorded there. Nine signal variants only: SMA 100/200/300 trend; 15/20/25% volatility
targets with SMA200 and a 1.5x cap; 126/189/252-session cross-asset momentum skipping
21 sessions and gated by SMA200. Central controls and stress rules were fixed too.
The studies by [Moskowitz, Ooi and Pedersen](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)
and [Moreira and Muir](https://conference.nber.org/confer/2016/LTAMs16/Moreira_Muir.pdf)
motivate trend persistence and reducing risk during high volatility. They do not
validate these particular ETF implementations.

Development is 2007–2015, validation 2016–2020, historical confirmation 2021–Sep2026.
Selection maximizes development CAGR among candidates with at least 10% smaller
drawdown than QQQ. It locked `{selected}` before validation. Validation failed;
selection was retained. Final confirmation and all predefined stresses were run
as one batch, without retuning. [Implementation notes](implementation_notes.md)
record one added zero-transaction-cost diagnostic and hash-integrity hardening.

The starting NAV date is **2006-12-29**, first fill **2007-01-03**, final mark
**2026-09-30**. All full-period comparisons share those dates. Warmup history is
excluded from returns. Subperiod metrics include the preceding NAV, preserving
their first daily return. Confirmation is historical reuse, not genuine out of sample.
Acceptance requires both objectives in full history, validation and confirmation,
plus joint adverse stress; no result qualifies.

## Net performance and curves

{headline}

DD days are longest calendar time underwater, including unrecovered episodes;
orders count filled adjustments, not round trips. Turnover is sum of absolute
trade notional/pretrade NAV per year (not divided by two). Mean gross is daily
closing holdings/NAV. `qqq_total_return` is a deliberately stricter, fully invested,
fractional gross benchmark with zero entry friction; `qqq_buy_hold` is the net
whole-order account. Both enter at the same first open. Dividends are reinvested
in both; terminal holdings are marked without a sale. Comparing against the net
benchmark instead does not rescue the nine candidates.

[Open standalone interactive equity and drawdown curves](results/curves.html).
The HTML contains Plotly inline and works offline. Exact daily values:
[equity CSV](results/full_equity.csv), [drawdown CSV](results/full_drawdown.csv).

{splits}

The selected rotation's development success (13.68% vs 12.06% QQQ CAGR, with much
less drawdown) reverses in validation (7.78% vs 23.94%). The entire neighborhood
fails later; changing to another lookback after seeing that would be selection bias.

## Exposure, leverage and signal attribution

{comparison}

Matched controls hold a constant QQQ weight learned only from each strategy's
development mean gross exposure; that weight is frozen thereafter. Matching total
gross exposure across different assets does not equalize market beta. The OLS
alpha is descriptive, not evidence of skill, and omits gold/bond factors. Thus the
rotation's positive QQQ-regression intercept cannot establish a timing edge.
The equal-weight three-ETF control reaches 10.16% CAGR/-21.66% DD versus rotation's
11.12%/-35.96%; most diversification benefit is available without selecting winners.

The SMA200 rule holds about 82% average gross exposure; its matched QQQ control
grows faster (13.45% vs 11.41%) with deeper drawdowns. Volatility-only QQQ has about
111% average gross and beta 0.92, so its near-match is not a free gain at the same
exposure. Fixed 1.25x QQQ demonstrates how much apparent growth can come from
leverage alone. The trend gate adds no return advantage in this cycle.

## Robustness, costs and uncertainty

{neighborhood}

The nine neighbors are all retained. There is no isolated full-period winning
parameter. Annual expanding-window selection (from 2016, training only through the
prior December) chooses rotation in 2016–17 and voltrend25 thereafter:

{wf_table}

This selector also fails. Choices, actual traded account and equity paths are saved;
performance is not computed by splicing independently capitalized strategy returns.

{sensitivities}

Baseline is Fixed pricing, 5 bp per-side aggregate spread/slippage, actual whole
trade shares, lagged Fed funds +150 bp borrowing. Fixed reflects the existing
paper-account fee observation; Tiered is a sensitivity. Joint adverse is 20 bp,
two-session signal delay, and funding +200 bp. Slippage is an assumption, not a
measured opening fill. No tested central or locked candidate is rescued by zero
transaction costs.
The volatility-only control barely passes full history with zero transaction
costs (16.40% CAGR), then fails at modeled costs (16.22%) and falls to 15.27% under
joint adverse conditions. It is a useful risk-control lead, not established alpha.

{costs}

Fee schedules use the repository's explicit Fixed/Tiered, exchange/clearing and
SEC/FINRA models, applied uniformly across historical dates rather than falsely
claiming reconstructed tariffs. See [IBKR commissions](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php).
Funding uses actual debit cash and ACT/360 calendar days, not leverage times a
flat annual penalty; Fed funds is a proxy for [IBKR's benchmark-plus-spread rates](https://www.interactivebrokers.com/en/trading/margin-rates.php).
The last cached DFF observation (2026-09-24) is carried through Sep30. Cash earns
zero base; the [broker-scaled cash-interest sensitivity](https://www.interactivebrokers.com/en/accounts/fees/pricing-interest-rates.php)
has little impact and reflects thresholds/account size approximately.

All intentional targets are <=1.5x, but drift can exceed this (max 1.63x in the
volatility-only control). No base open/close exposure exceeds 2x. This does not
certify intraday margin or house requirements. Previous-close order sizing reserves
1% cash on unlevered decisions. The resized-purchase counts disclose cases where
opening gaps/postcost exposure required reducing a planned buy after observing the
open; these are approximate opening-session fills, not exact MOO auction fills.

Fresh $5,000 restarts test present-day small-account sizing rather than a large
account grown from 2007. Restart benchmarks enter at the new first open; their
first overnight return therefore differs from continuous subperiods:

{restart_table}

Regime checks expose why drawdown reduction is not stable across crises:

{regimes}

QQQ-only 2001–2006 diagnostic (starting NAV 2000-12-29, after the 2000 crash had
already begun):

{dotcom_table}

Trend helps greatly in this sustained bear market, but that previously observed
period was not used to overturn the failed later validation. This is not a test
of the complete peak-to-trough 2000 crash, and GLD is not synthetically backfilled.

Paired circular-block bootstrap on 2016–Sep2026, 2,000 resamples, 63 sessions/block,
seed 20261001:

{uncertain}

The intervals concern annualized **log-growth differences**, not percentage-point
CAGR differences. The centered max-statistic test covers all nine signal variants;
it does not adjust away the repository's earlier experiments, chosen ETF universe,
or publication selection. No positive excess-growth claim is significant. The
selected rotation has a -9.68% annual log-growth gap with a wide interval spanning
zero; resampled simultaneous-objective frequency is only 2.95%. This frequency is
not a probability of future success. Dependence across long market regimes and
vendor/execution uncertainty remain beyond what this bootstrap can establish.

Metric conventions: CAGR uses elapsed calendar days/365.25. Sharpe is daily mean
excess return divided by sample standard deviation of daily excess return, times
sqrt(252). Excess return subtracts lagged DFF times actual elapsed days/360.
Sortino uses the same numerator and sqrt(mean(min(excess,0)^2)) across **all** days,
times sqrt(252). The rate is a risk-free proxy; account cash follows its separate
modeled policy. Zero-rate Sharpe is also in the CSVs for legacy reconciliation.

## Decision and evidence that would change it

Reject the selected rotation and trend-gated variants as solutions to the stated
joint objective. Preserve simple trend as a documented crisis-protection tradeoff,
not a claim of higher growth. Prefer **further research**, with the existing fixed
volatility-only control as the narrow lead: its risk reduction is meaningful, but
its return edge disappears under realistic costs, worse financing or slower fills.
Do not tune its volatility window/target further on this history in this cycle.

A subsequent cycle should pre-register the unchanged 63-day/20%/1.5x volatility
rule on additional liquid equity ETFs and prospective observations, with a real
dividend/whole-share cash ledger and measured opening execution. Require growth
above the identical-period QQQ reference, at least 10% lower drawdown, persistence
under adverse costs, and economically positive excess growth outside the selected
asset/regime. A repeatable failure should reject the return-enhancement claim;
success across independent regimes could justify execution-only paper evaluation.
Paper trading alone will not establish a multi-decade drawdown claim.

Remaining limitations: reused history and multiple testing; selected asset set;
ideal fractional gross dividend reinvestment on adjusted prices (not pay-date cash
or a whole-share DRIP ledger); no dividend withholding/personal taxes, consistently
for benchmark and strategies; daily resolution and approximate opening fills;
historical tariff/funding proxies; and no independently sourced long-history price
validation. These matter especially for a marginal control near the benchmark.

## Reproduction and artifacts

Run from repository root using the pinned existing environment. Exact replay is
offline once frozen inputs are present. `uv run --no-sync python` may replace the
Windows interpreter path below.

```powershell
.venv/Scripts/python.exe research/qqq_research_cycle/reproduce_legacy.py
.venv/Scripts/python.exe research/qqq_research_cycle/prepare_inputs.py
.venv/Scripts/python.exe -m horizon_trader.backtest.research_cycle --stage develop
.venv/Scripts/python.exe -m horizon_trader.backtest.research_cycle --stage validate
.venv/Scripts/python.exe -m horizon_trader.backtest.research_cycle --stage confirm
.venv/Scripts/python.exe research/qqq_research_cycle/make_report.py
.venv/Scripts/python.exe research/qqq_research_cycle/verify_results.py
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp data/tmp/cycle_verification
```

`fetch_raw.py` is the explicit network retrieval step if reconstructing missing raw
inputs. Exact old prices require the frozen snapshot, since Yahoo can revise data.
`prepare_inputs.py` preserves an existing snapshot. Inputs are in git-ignored
`data/research_cycle_2026_10_01/inputs/` and **must be preserved/copied with this
research** for exact replay; SHA256s are stored in its manifest. Stage manifests
record Python/numpy/pandas and code/config hashes. The runner validates input and
protocol hashes and refuses a changed locked selection. No API keys are in artifacts.

The [experiment ledger](results/experiment_ledger.csv) contains {len(recorded)} rows
covering every candidate/control, period, stress, restart, dotcom and walk-forward
result with rejection reasons. These rows are related diagnostics, not independent
trials; the signal search was nine variants. Additional files include all orders,
daily cash/cost/exposure accounts, annual and regime metrics, uncertainty, selected
parameters, legacy snapshots, and the self-contained curves. Files in the original
dirty worktree were preserved; only clean legacy simulator/analytics code and their
tests were modified alongside new research files.

Verification: the full repository suite passed 393 tests, and three subsequently
added statistical tests also passed. Changed/new code passes Ruff. The saved
development account is replayed bit-exactly by `verify_results.py`, which also
checks capital identities, signal/fill ordering, comparison dates and trial coverage.
Three existing numpy warnings occur in the fundamentals test with insufficient
observations. No rendering screenshot was captured; curves are generated by Plotly
from the same saved daily equity used for the tables.
"""
    (HERE / "report.md").write_text(text, encoding="utf-8")
    hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [CONFIG, HERE / "protocol.md", HERE / "report.md", *sorted(OUT.glob("*.csv"))]
    }
    (OUT / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote report, offline curves, and {len(recorded)} ledger rows")


if __name__ == "__main__":
    main()
