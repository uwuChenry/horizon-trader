"""Bounded portfolio complementarity screen; local caches only, no executable allocation.

    .venv/Scripts/python.exe research/portfolio_data_review_2026_10_01/analyze_portfolio.py

Fixed before reading these diagnostics: representative core, baseline ORB, QQQ
noise; inverse-volatility weights estimated through 2023, frozen thereafter.
No parameter search. Existing simulated fill assumptions are inherited.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.backtest.research_stats import drawdown_days, risk_free
from horizon_trader.backtest.run import run_targets, target_histories
from horizon_trader.config import DEFAULT_CONFIG, load_settings
from horizon_trader.execution.costs import IBKR_PLANS
from horizon_trader.intraday import market_momentum as mm
from horizon_trader.sleeves.risk_parity import RiskParitySleeve

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent / "results"
INITIAL = "2021-11-01"
FIRST_RETURN = "2021-11-02"
END = "2026-09-24"
SPLIT = "2024-01-01"
PRIMARY = ["daily_core_fixed", "orb_fixed", "qqq_noise_fixed"]
SAVED = {
    "legacy_daily_tiered": "20260925-163616_blend-daily-book-only-reference",
    "legacy_orb_tiered": "20260925-163616_blend-orb-only",
    "legacy_noise_tiered": "20260925-163616_blend-qqq-noise-only",
    "orb_fixed_original": "20260925-031640_orb-top1-1atr-stop-limit-0c-5k-fixed",
    "winners_tiered_price_only": "20260926-040915_winners-momentum-12-1-top-10-5k-net",
}
SOURCES = []


def read(path: Path) -> pd.DataFrame:
    SOURCES.append(
        {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    )
    return pd.read_parquet(path)


def orb_replay(fills: pd.DataFrame, calendar: pd.DatetimeIndex, plan: str, slip=0.0):
    """Replay saved baseline filled trades, preserving selection and fill outcomes.

    Initial full-calendar replay must reproduce the saved Fixed curve to <1e-8.
    Additional adverse slip applies to BOTH fills including closing auction.
    """
    fills = fills.assign(date=fills.entry_time.dt.tz_localize(None).dt.normalize())
    by_day = dict(tuple(fills.groupby("date")))
    account, model, curve, trades = 5000.0, IBKR_PLANS[plan], {}, []
    for day in calendar:
        before = account
        if day in by_day:
            for r in by_day[day].itertuples():
                quantity = np.floor(
                    min(0.01 * before / abs(r.entry_px - r.stop_px), 4 * before / r.entry_px)
                )
                if quantity < 1:
                    continue
                entry, exit_ = r.entry_px + r.side * slip, r.exit_px - r.side * slip
                costs = model.total(r.side * quantity, entry) + model.total(
                    -r.side * quantity, exit_
                )
                pnl = r.side * quantity * (exit_ - entry) - costs
                account += pnl
                trades.append(
                    {
                        "date": day,
                        "quantity": quantity,
                        "entry": entry,
                        "exit": exit_,
                        "side": r.side,
                        "symbol": r.symbol,
                        "costs": costs,
                        "pnl": pnl,
                        "entry_gross_exposure": quantity * entry / before,
                    }
                )
        curve[day] = account
    initial = calendar[0] - pd.Timedelta(days=1)
    return pd.concat([pd.Series({initial: 5000.0}), pd.Series(curve)]), pd.DataFrame(trades)


def stats(ret: pd.Series, rf: pd.Series, previous: pd.Timestamp) -> dict:
    ex = ret - rf.reindex(ret.index)
    downside = np.sqrt(np.minimum(ex, 0).pow(2).mean())
    equity = pd.concat([pd.Series({previous: 1.0}), (1 + ret).cumprod()])
    years = (ret.index[-1] - previous).days / 365.25
    return {
        "start_nav_date": str(previous.date()),
        "end": str(ret.index[-1].date()),
        "sessions": len(ret),
        "cagr": equity.iloc[-1] ** (1 / years) - 1,
        "sharpe_excess": ex.mean() / ex.std(ddof=1) * np.sqrt(252),
        "sortino_excess": ex.mean() / downside * np.sqrt(252) if downside else np.nan,
        "sharpe_zero": ret.mean() / ret.std(ddof=1) * np.sqrt(252),
        "volatility": ret.std(ddof=1) * np.sqrt(252),
        "max_drawdown": (equity / equity.cummax() - 1).min(),
        "drawdown_days": drawdown_days(equity),
        "mean_excess_annual": ex.mean() * 252,
    }


def period_tables(returns: pd.DataFrame, rf: pd.Series) -> pd.DataFrame:
    rows = []
    for period, start, end in [
        ("full", FIRST_RETURN, END),
        ("train_2021_23", FIRST_RETURN, "2023-12-31"),
        ("test_2024_plus", SPLIT, END),
        ("inflation_2022", "2022-01-01", "2022-12-31"),
        ("post_publication", "2024-05-15", END),
    ]:
        chunk = returns.loc[start:end]
        if chunk.empty:
            continue
        pos = returns.index.get_loc(chunk.index[0])
        previous = returns.index[pos - 1] if pos else pd.Timestamp(INITIAL)
        for name in returns:
            valid = chunk[name].dropna()
            if len(valid) < 20:
                continue
            # Supplementary winners do not receive an invented 2021 starting NAV.
            prior = (
                previous
                if valid.index[0] == chunk.index[0]
                else returns.index[returns.index.get_loc(valid.index[0]) - 1]
            )
            rows.append({"period": period, "strategy": name, **stats(valid, rf, prior)})
    return pd.DataFrame(rows)


def paired_sharpe_ci(ret: pd.DataFrame, rf: pd.Series) -> pd.DataFrame:
    """Descriptive 95% intervals, paired 21-session circular blocks, 1,000 draws."""
    rng = np.random.default_rng(20261001)
    rows = []
    increments = []
    for period, dates in [("full", ret.index), ("test_2024_plus", ret.loc[SPLIT:].index)]:
        values = ret.loc[dates].sub(rf.reindex(dates), axis=0).to_numpy()
        n = len(values)
        ix = (rng.integers(n, size=(1000, int(np.ceil(n / 21)), 1)) + np.arange(21)) % n
        ix = ix.reshape(1000, -1)[:, :n]
        sample = values[ix]
        sharpes = sample.mean(axis=1) / sample.std(axis=1, ddof=1) * np.sqrt(252)
        lower, upper = np.quantile(sharpes, [0.025, 0.975], axis=0)
        for i, name in enumerate(ret):
            rows.append(
                {
                    "period": period,
                    "strategy": name,
                    "ci95_low": lower[i],
                    "ci95_high": upper[i],
                    "samples": 1000,
                    "block_sessions": 21,
                    "multiple_testing_adjusted": False,
                }
            )
            if name != "daily_core_fixed":
                baseline = list(ret.columns).index("daily_core_fixed")
                differences = sharpes[:, i] - sharpes[:, baseline]
                lo, hi = np.quantile(differences, [0.025, 0.975])
                observed = values.mean(axis=0) / values.std(axis=0, ddof=1) * np.sqrt(252)
                increments.append(
                    {
                        "period": period,
                        "strategy": name,
                        "reference": "daily_core_fixed",
                        "incremental_excess_sharpe": observed[i] - observed[baseline],
                        "ci95_low": lo,
                        "ci95_high": hi,
                        "samples": 1000,
                        "block_sessions": 21,
                        "multiple_testing_adjusted": False,
                    }
                )
    pd.DataFrame(increments).to_csv(OUT / "incremental_sharpe.csv", index=False)
    return pd.DataFrame(rows)


def correlation_heatmap(returns: pd.DataFrame, names: list[str]) -> None:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    periods = [
        ("Full 2021–2026", returns),
        ("Training 2021–2023", returns.loc[:"2023-12-31"]),
        ("Reused test 2024–2026", returns.loc[SPLIT:]),
    ]
    labels = ["Daily core", "ORB baseline", "QQQ noise", "Risk parity", "QQQ total return"]
    fig = make_subplots(
        rows=1, cols=3, subplot_titles=[p[0] for p in periods], horizontal_spacing=0.10
    )
    for column, (_, frame) in enumerate(periods, 1):
        matrix = frame[names].corr().to_numpy()
        fig.add_trace(
            go.Heatmap(
                z=matrix,
                x=labels,
                y=labels,
                zmin=-1,
                zmax=1,
                colorscale="RdBu",
                reversescale=True,
                text=np.round(matrix, 2),
                texttemplate="%{text:.2f}",
                showscale=column == 3,
                hovertemplate="%{y} / %{x}<br>correlation %{z:.3f}<extra></extra>",
            ),
            row=1,
            col=column,
        )
    fig.update_layout(
        template="plotly_white",
        height=570,
        width=1500,
        title="Complementarity of modeled daily returns — Fixed costs, $5k starts",
        margin=dict(l=105, r=50, t=100, b=125),
    )
    fig.add_annotation(
        x=0,
        y=-0.29,
        xref="paper",
        yref="paper",
        showarrow=False,
        xanchor="left",
        text="2021-11-02 to 2026-09-24. Local simulations; prior history reused. "
        "Correlations do not establish executable portfolio returns.",
    )
    fig.write_html(OUT.parent / "correlation_heatmap.html", include_plotlyjs=True, full_html=True)


def equity_drawdown_figure(returns: pd.DataFrame) -> None:
    """Append an exportable Plotly figure, sharing the existing offline JS bundle."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    names = {
        "qqq_total_return": "QQQ total return",
        "daily_core_fixed": "Daily core · Fixed",
        "orb_fixed": "ORB baseline · Fixed",
        "qqq_noise_fixed": "QQQ noise · Fixed",
        "equal_risk_frozen": "SCREEN · Frozen inverse volatility",
        "reduced_overlay": "SCREEN · Reduced overlay",
        "reduced_overlay_cost_stress": "SCREEN · Stressed reduced overlay",
    }
    colors = ["#343a40", "#1f77b4", "#d95f02", "#2ca02c", "#9467bd", "#e7298a", "#a6761d"]
    initial = pd.DataFrame(5000.0, index=[pd.Timestamp(INITIAL)], columns=list(names))
    equity = pd.concat([initial, 5000 * (1 + returns[list(names)]).cumprod()])
    drawdown = equity / equity.cummax() - 1
    equity.to_csv(OUT / "plotted_equity.csv", index_label="date")
    drawdown.to_csv(OUT / "plotted_drawdown.csv", index_label="date")
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.09,
        subplot_titles=["Normalized wealth from $5,000", "Drawdown from prior peak"],
    )
    for (name, label), color in zip(names.items(), colors, strict=True):
        line = dict(color=color, width=2, dash="dash" if label.startswith("SCREEN") else "solid")
        for row, values in [(1, equity[name]), (2, drawdown[name])]:
            fig.add_trace(
                go.Scatter(
                    x=values.index,
                    y=values,
                    name=label,
                    legendgroup=name,
                    showlegend=row == 1,
                    mode="lines",
                    line=line,
                ),
                row=row,
                col=1,
            )
    for row in [1, 2]:
        fig.add_vline(
            x=pd.Timestamp(SPLIT).timestamp() * 1000,
            line_dash="dot",
            line_color="#666",
            row=row,
            col=1,
        )
    fig.update_yaxes(title_text="USD (log scale)", type="log", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown", tickformat=".0%", row=2, col=1)
    fig.update_layout(
        template="plotly_white",
        width=1500,
        height=1000,
        title="Modeled standalone returns and SCREENING ARITHMETIC blends",
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.08),
        margin=dict(l=90, r=35, t=100, b=170),
    )
    fig.add_annotation(
        x=0,
        y=-0.23,
        xref="paper",
        yref="paper",
        showarrow=False,
        xanchor="left",
        text="Dashed curves scale independent net return streams; they are NOT "
        "executable portfolio backtests. Dotted line: training ends / reused "
        "2024+ test begins. All cash yields are zero.",
    )
    html = OUT.parent / "correlation_heatmap.html"
    page = html.read_text(encoding="utf-8")
    chart = fig.to_html(
        include_plotlyjs=False,
        full_html=False,
        config={
            "toImageButtonOptions": {
                "format": "png",
                "filename": "portfolio_screening_equity_drawdown",
                "scale": 2,
            }
        },
    )
    section = '<section id="equity-drawdown"><h2>Equity and drawdown</h2>' + chart + "</section>"
    html.write_text(page.replace("</body>", section + "</body>"), encoding="utf-8")


def experiment_ledger(table: pd.DataFrame, legacy: pd.DataFrame, blends: dict) -> None:
    """Preserve every declared stream and screen, including unsuccessful controls."""
    descriptions = {
        "daily_core_fixed": (
            "standalone",
            "Existing configured daily book",
            "Fails full-period return objective; retained as core comparison",
        ),
        "risk_parity_fixed": (
            "standalone",
            "Existing unlevered 756-session inverse-vol sleeve",
            "Fails full-period return objective; limited incremental diversification",
        ),
        "orb_fixed": (
            "standalone",
            "Untuned baseline ORB with measured saved fill outcomes",
            "Fails full-period return objective; complementary signal needs execution validation",
        ),
        "qqq_noise_fixed": (
            "standalone",
            "Existing QQQ noise rule with Fixed fees",
            "Marginal CAGR lead over QQQ erased by 1c stress; shared-account replay candidate",
        ),
        "orb_tiered": (
            "cost_sensitivity",
            "Reprice same saved baseline fills using Tiered fees",
            "Alternate plan sensitivity; current account Tiered pricing is unconfirmed",
        ),
        "qqq_noise_tiered": (
            "cost_sensitivity",
            "Reprice same QQQ noise rule using Tiered fees",
            "Alternate plan sensitivity; not the primary Fixed comparison",
        ),
        "orb_fixed_extra_1c": (
            "execution_sensitivity",
            "Add 1c adverse movement to each ORB fill",
            "Cost deterioration supports collecting actual execution measurements",
        ),
        "qqq_noise_fixed_1c": (
            "execution_sensitivity",
            "Increase non-auction noise slippage from 0.5c to 1c",
            "Erases marginal full-period CAGR lead; inherited auction assumptions remain",
        ),
        "qqq_total_return": (
            "benchmark",
            "Gross reinvested QQQ returns on common dates",
            "Reference; no claimed signal edge",
        ),
        "winners_tiered_price_only": (
            "supplementary",
            "Saved 12-1 top-ten stock momentum",
            "Shorter sample, Tiered/fractional/price-only; excluded from blend weights",
        ),
    }
    rows = []
    for name in table.strategy.unique():
        if name in blends:
            classification = "delete_one_screen" if name.startswith("delete_") else "return_screen"
            reason = (
                "Remove one frozen weight to zero-yield cash"
                if name.startswith("delete_")
                else "Fixed illustrative blend of standalone net returns; no parameter search"
            )
            decision = "Prioritize shared-account replay; screening arithmetic is not deployable"
        else:
            classification, reason, decision = descriptions[name]
        row = {
            "strategy": name,
            "classification": classification,
            "reason_included": reason,
            "decision": decision,
            "portfolio_objective_acceptance": "not assessed for synthetic blends"
            if name in blends
            else "see standalone metrics and limitations",
        }
        for period, prefix in [("full", "full"), ("test_2024_plus", "reused_test")]:
            metric = table[(table.strategy == name) & (table.period == period)].iloc[0]
            for key in ["cagr", "max_drawdown", "sharpe_excess", "sortino_excess", "sessions"]:
                row[f"{prefix}_{key}"] = metric[key]
        rows.append(row)
    for name in legacy.strategy.unique():
        rows.append(
            {
                "strategy": name,
                "classification": "historical_reconciliation",
                "reason_included": "Reconcile previously published Tiered return arithmetic",
                "decision": "Arithmetic reproduced; joint capital and execution remain unverified",
                "portfolio_objective_acceptance": "not assessed for synthetic blends",
                **{
                    f"full_{key}": legacy[
                        (legacy.strategy == name) & (legacy.period == "full")
                    ].iloc[0][key]
                    for key in [
                        "cagr",
                        "max_drawdown",
                        "sharpe_excess",
                        "sortino_excess",
                        "sessions",
                    ]
                },
            }
        )
    pd.DataFrame(rows).to_csv(OUT / "experiment_ledger.csv", index=False)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    saved = {}
    for name, run in SAVED.items():
        path = ROOT / "data/results" / run
        saved[name] = read(path / "equity.parquet")["equity"]
        SOURCES.append(
            {
                "path": str((path / "meta.json").resolve()),
                "sha256": hashlib.sha256((path / "meta.json").read_bytes()).hexdigest(),
            }
        )
    orb_path = ROOT / "data/results" / SAVED["orb_fixed_original"] / "trades.parquet"
    orb_fills = read(orb_path)
    replay, _ = orb_replay(orb_fills, saved["orb_fixed_original"].index[1:], "fixed")
    replay_error = float((replay - saved["orb_fixed_original"]).abs().max())
    if replay_error > 1e-8:
        raise ValueError(f"ORB saved fill replay differs: {replay_error}")

    frozen_config = OUT / "effective_daily_settings.json"
    loaded_config = frozen_config if frozen_config.exists() else DEFAULT_CONFIG
    loaded_config_hash = hashlib.sha256(loaded_config.read_bytes()).hexdigest()
    settings = load_settings(loaded_config)
    settings.costs.plan = "fixed"
    frozen_config.write_text(
        json.dumps(settings.model_dump(exclude={"live"}), indent=2) + "\n", encoding="utf-8"
    )
    frames = {
        symbol: read(ROOT / "data/bars" / f"{symbol}.parquet").loc[:END]
        for symbol in settings.universe
    }
    bars = {
        field: pd.DataFrame({s: f[field] for s, f in frames.items()}).sort_index()
        for field in ["open", "close"]
    }
    targets = target_histories(settings, bars["close"])["combined"]
    core = run_targets(targets, bars, INITIAL, settings)
    rp = run_targets(
        RiskParitySleeve("risk_parity").weights_history(bars["close"]), bars, INITIAL, settings
    )
    calendar = core.equity.index[1:]
    curves = {"daily_core_fixed": core.equity, "risk_parity_fixed": rp.equity}
    execution = []
    for plan in ["fixed", "tiered"]:
        curves[f"orb_{plan}"], fills = orb_replay(orb_fills, calendar, plan)
        fills.assign(strategy=f"orb_{plan}").to_csv(OUT / f"orb_{plan}_fills.csv", index=False)
        execution.append(
            {
                "strategy": f"orb_{plan}",
                "round_trips": len(fills),
                "fees": fills.costs.sum(),
                "max_observed_entry_exposure": fills.entry_gross_exposure.max(),
            }
        )
    curves["orb_fixed_extra_1c"], _ = orb_replay(orb_fills, calendar, "fixed", slip=0.01)

    # Direct read bypasses build/load_bars, which otherwise scans and updates caches.
    minute = read(ROOT / "data/massive/derived/minute_QQQ.parquet")
    daily = read(ROOT / "data/massive/derived/day_QQQ.parquet")
    qb = mm.make_bars(minute, daily)
    noise = mm.noise_trades(qb)
    sigma_ok = mm.noise_sigma(qb.close, qb.daily["open"])[list(mm.CHECKS)].notna().any(axis=1)
    valid = qb.close.index[(sigma_ok & mm.daily_vol(qb.daily).notna()).to_numpy()]
    if not calendar.isin(valid).all():
        raise ValueError("QQQ missing sessions on common calendar")
    for plan, slip, label in [
        ("fixed", 0.005, "qqq_noise_fixed"),
        ("tiered", 0.005, "qqq_noise_tiered"),
        ("fixed", 0.01, "qqq_noise_fixed_1c"),
    ]:
        account = mm.Account(equity=5000, plan=plan, slippage=slip)
        curves[label], fills = mm.run_portfolio(
            noise[noise.date.isin(calendar)], qb.daily, account, calendar
        )
        fills.assign(strategy=label).to_csv(OUT / f"{label}_fills.csv", index=False)
        execution.append(
            {
                "strategy": label,
                "round_trips": len(fills),
                "fees": fills.costs.sum(),
                "max_observed_entry_exposure": fills.lev.max(),
            }
        )
    for name, result in [("daily_core_fixed", core), ("risk_parity_fixed", rp)]:
        result.trades.to_csv(OUT / f"{name}_fills.csv", index=False)
        execution.append(
            {"strategy": name, "orders": len(result.trades), "fees": result.trades.commission.sum()}
        )

    rates = read(ROOT / "data/research_cycle_2026_10_01/inputs/dff.parquet")["ff"]
    dates = pd.DatetimeIndex([pd.Timestamp(INITIAL), *calendar])
    rf = risk_free(dates, rates).loc[calendar]
    returns = pd.DataFrame(
        {
            name: curve.pct_change(fill_method=None).reindex(calendar)
            for name, curve in curves.items()
        }
    )
    if returns.isna().any().any():
        raise ValueError("Primary streams must share every session; no backfills allowed")
    returns["qqq_total_return"] = bars["close"].QQQ.pct_change(fill_method=None).reindex(calendar)
    returns["winners_tiered_price_only"] = (
        saved["winners_tiered_price_only"].pct_change(fill_method=None).reindex(calendar)
    )
    training = returns.loc[:"2023-12-31", PRIMARY]
    inverse_vol = 1 / training.std(ddof=1)
    weights = inverse_vol / inverse_vol.sum()
    blends = {
        "equal_risk_frozen": returns[PRIMARY].mul(weights).sum(axis=1),
        "daily_plus_orb": returns.daily_core_fixed + returns.orb_fixed,
        "daily_plus_noise": returns.daily_core_fixed + returns.qqq_noise_fixed,
        "daily_plus_both": returns[PRIMARY].sum(axis=1),
        "reduced_overlay": returns.daily_core_fixed
        + 0.25 * returns.orb_fixed
        + 0.5 * returns.qqq_noise_fixed,
        "reduced_overlay_cost_stress": returns.daily_core_fixed
        + 0.25 * returns.orb_fixed_extra_1c
        + 0.5 * returns.qqq_noise_fixed_1c,
    }
    for removed in PRIMARY:
        kept = [s for s in PRIMARY if s != removed]
        blends[f"delete_{removed}_cash"] = returns[kept].mul(weights[kept]).sum(axis=1)
    blend_frame = pd.DataFrame(blends)
    combined = pd.concat([returns, blend_frame], axis=1)
    metric_table = period_tables(combined, rf)
    metric_table.to_csv(OUT / "metrics.csv", index=False)
    combined.to_csv(OUT / "returns.csv", index_label="date")
    rf.rename("dff_cash_hurdle").to_csv(OUT / "cash_benchmark.csv", index_label="date")
    pd.DataFrame(execution).to_csv(OUT / "execution_summary.csv", index=False)
    weights.rename("weight").to_csv(OUT / "frozen_inverse_vol_weights.csv", index_label="strategy")
    paired_sharpe_ci(
        combined[
            PRIMARY + ["equal_risk_frozen", "daily_plus_orb", "daily_plus_noise", "reduced_overlay"]
        ],
        rf,
    ).to_csv(OUT / "sharpe_uncertainty.csv", index=False)

    # Conditioning uses observed stress labels for diagnostics, not trading decisions.
    correlation_names = PRIMARY + ["risk_parity_fixed", "qqq_total_return"]
    qeq = (1 + returns.qqq_total_return).cumprod()
    qdd = qeq / qeq.cummax().clip(lower=1.0) - 1
    threshold = returns.loc[:"2023-12-31", "qqq_total_return"].quantile(0.1)
    masks = {
        "full": pd.Series(True, index=calendar),
        "train_2021_23": calendar < pd.Timestamp(SPLIT),
        "test_2024_plus": calendar >= pd.Timestamp(SPLIT),
        "inflation_2022": calendar.year == 2022,
        "qqq_drawdown_10pct": qdd < -0.10,
        "qqq_bad_day_train_decile": returns.qqq_total_return <= threshold,
        "core_down_day": returns.daily_core_fixed < 0,
    }
    correlations = []
    conditional = []
    for condition, mask in masks.items():
        chunk = returns.loc[mask, correlation_names]
        corr = chunk.corr()
        for a in correlation_names:
            conditional.append(
                {
                    "condition": condition,
                    "strategy": a,
                    "sessions": len(chunk),
                    "mean_daily_return": chunk[a].mean(),
                    "loss_fraction": (chunk[a] < 0).mean(),
                }
            )
            for b in correlation_names:
                correlations.append(
                    {
                        "condition": condition,
                        "a": a,
                        "b": b,
                        "sessions": len(chunk),
                        "correlation": corr.loc[a, b],
                    }
                )
    pd.DataFrame(correlations).to_csv(OUT / "conditional_correlations.csv", index=False)
    pd.DataFrame(conditional).to_csv(OUT / "conditional_returns.csv", index=False)
    correlation_heatmap(returns, correlation_names)
    equity_drawdown_figure(combined)
    supplement = returns[correlation_names + ["winners_tiered_price_only"]].dropna()
    supplement.corr().to_csv(OUT / "winners_supplementary_correlations.csv")

    # Arithmetic reconciliation only: the exact saved Tiered inputs used by mix.py.
    legacy = pd.DataFrame(
        {
            k: saved[k].pct_change(fill_method=None)
            for k in ["legacy_daily_tiered", "legacy_orb_tiered", "legacy_noise_tiered"]
        }
    ).dropna()
    legacy["legacy_daily_plus_noise"] = legacy.legacy_daily_tiered + legacy.legacy_noise_tiered
    legacy["legacy_daily_plus_orb"] = legacy.legacy_daily_tiered + legacy.legacy_orb_tiered
    legacy["legacy_all_three"] = legacy[
        ["legacy_daily_tiered", "legacy_orb_tiered", "legacy_noise_tiered"]
    ].sum(axis=1)
    legacy_table = period_tables(legacy, rf)
    legacy_table.to_csv(OUT / "legacy_mix_reconciliation.csv", index=False)
    experiment_ledger(metric_table, legacy_table, blends)
    metadata = {
        "command": (
            ".venv/Scripts/python.exe "
            "research/portfolio_data_review_2026_10_01/analyze_portfolio.py"
        ),
        "scope": "Descriptive screening; synthetic return blends, not capital/margin/fill replay",
        "initial_nav": INITIAL,
        "first_return": FIRST_RETURN,
        "end": END,
        "selection": "Representative existing baseline sleeves, no parameter or blend search",
        "training_end": "2023-12-31",
        "test_start": SPLIT,
        "risk_weights": weights.to_dict(),
        "orb_saved_curve_replay_max_error": replay_error,
        "cash_convention": (
            "Zero cash income in source returns. Portfolio excess = sum(scaled raw source returns) "
            "minus ONE DFF hurdle; no rf added per intraday sleeve."
        ),
        "cost_convention": (
            "Primary replays Fixed $5k; historical Tiered outputs isolated. Scaling already-net "
            "returns does not reprice fee minima or whole shares at portfolio equity."
        ),
        "sources": SOURCES,
        "daily_settings_snapshot": settings.model_dump(exclude={"live"}),
        "loaded_config_path": str(loaded_config.resolve()),
        "loaded_config_sha256": loaded_config_hash,
        "effective_config_path": str(frozen_config.resolve()),
        "effective_config_sha256": hashlib.sha256(frozen_config.read_bytes()).hexdigest(),
        "metric_conventions": {
            "sharpe": "Mean daily excess / sample standard deviation of excess * sqrt(252)",
            "sortino": "Mean daily excess / RMS(min(daily excess,0)) * sqrt(252), all sessions",
            "cagr": "Compounded endpoint wealth using actual elapsed calendar days /365.25",
        },
        "screened_blends": list(blends),
        "prior_research": (
            "Entire historical sample was used in earlier repository research; no untouched test."
        ),
        "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "code_hashes": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                Path(__file__),
                *[
                    ROOT / "src/horizon_trader" / filename
                    for filename in [
                        "backtest/research_stats.py",
                        "backtest/run.py",
                        "backtest/sim.py",
                        "execution/costs.py",
                        "execution/paper_sim.py",
                        "execution/rebalance.py",
                        "intraday/market_momentum.py",
                        "sleeves/momentum.py",
                        "sleeves/trend.py",
                        "sleeves/vol_managed.py",
                        "sleeves/mean_reversion.py",
                        "sleeves/risk_parity.py",
                        "portfolio/risk.py",
                        "portfolio/combine.py",
                    ]
                ],
            ]
            if path.exists()
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(
        period_tables(combined, rf)
        .query("period == 'test_2024_plus'")[
            ["strategy", "cagr", "sharpe_excess", "sharpe_zero", "max_drawdown"]
        ]
        .to_string(index=False)
    )
    print("Training-frozen inverse-vol weights:", weights.to_dict())
    print("ORB original replay discrepancy:", replay_error)
    print("Saved", OUT)


if __name__ == "__main__":
    main()
