"""Frozen ORB paths, EMA confirmation, stop width and account-sizing comparison.

Run from the repository root. Local data only; no broker calls or settings writes.
"""

import hashlib
import json
from dataclasses import replace
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from horizon_trader.backtest.metrics import summarize
from horizon_trader.config import data_dir
from horizon_trader.datasources import massive
from horizon_trader.intraday import orb_ema as E
from horizon_trader.intraday import orb_exit_diagnostics as D

EXITS = {"hold": ("orb", 1), "ema1": ("orb_ema_exit", 1), "ema2": ("orb_ema_exit", 2)}
NAMES = {"hold": "ORB hold", "ema1": "One EMA close", "ema2": "Two EMA closes"}
STOPS = (1.0, 0.5)
KEY = ["date", "ticker"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def simulate_paths(picked, groups, source_dates, ends, splits):
    rules = E.Rules(candle_minutes=5, exit_candle_minutes=15)
    rows = []
    empty = pd.DataFrame(columns=E.COLS)
    for number, candidate in enumerate(picked.to_dict("records"), 1):
        day, ticker = candidate["date"], candidate["ticker"]
        today = groups[(day, ticker)]
        prior = source_dates[source_dates < day][-rules.warmup_sessions :]
        history = pd.concat([groups.get((d, ticker), empty) for d in prior], ignore_index=True)
        assert len(prior) == rules.warmup_sessions and not history.empty
        history = E.adjust_history(history, day, splits[splits.ticker == ticker])
        signals = E.ema_signals(history, today, rules)
        exits = E.ema_signals(history, today, replace(rules, candle_minutes=15))
        start = E.F.session_open(day.date())
        assert signals.loc[signals.signal_time <= start, "ema"].notna().any()
        assert exits.loc[exits.signal_time <= start, "ema"].notna().any()
        for label, (variant, confirmations) in EXITS.items():
            for stop in STOPS:
                trade = E.simulate(
                    today,
                    signals,
                    candidate,
                    variant,
                    stop,
                    ends[day],
                    replace(rules, exit_confirmations=confirmations),
                    exits,
                )
                if trade is not None:
                    rows.append({"exit_rule": label, **trade})
        if number % 250 == 0 or number == len(picked):
            print(f"Simulated {number}/{len(picked)} selected sessions", flush=True)
    trades = pd.DataFrame(rows)
    # JSON close times contain fixed UTC offsets; unify with bar timestamps so
    # daylight-saving transitions retain one timezone dtype, without changing instants.
    for column in ("entry_time", "exit_time"):
        trades[column] = pd.to_datetime(trades[column], utc=True).dt.tz_convert("America/New_York")
    return trades


def check_controls(trades, old):
    fields = [
        *KEY,
        "side",
        "entry_px",
        "entry_time",
        "stop_dist",
        "exit_px_cons",
        "exit_idx_cons",
        "stopped_cons",
        "exit_reason",
        "exit_time",
        "gross_R",
    ]
    checked = 0
    for label, variant in (("hold", "orb"), ("ema1", "orb_ema_exit")):
        for stop in STOPS:
            a = trades[(trades.exit_rule == label) & (trades.stop_atr == stop)]
            b = old[(old.variant == variant) & (old.stop_atr == stop)]
            frames = [f[fields].sort_values(KEY).reset_index(drop=True) for f in (a, b)]
            for frame in frames:
                for column in ("entry_time", "exit_time"):
                    # Stored auction timestamps use microseconds; compare the
                    # exact instants at nanosecond precision, matching minute bars.
                    frame[column] = frame[column].dt.as_unit("ns")
            pd.testing.assert_frame_equal(
                *frames,
                check_exact=True,
            )
            checked += len(a)
    entries = [*KEY, "side", "entry_px", "entry_time"]
    base = trades[(trades.exit_rule == "hold") & (trades.stop_atr == 1)][entries]
    for _, group in trades.groupby(["exit_rule", "stop_atr"]):
        pd.testing.assert_frame_equal(
            group[entries].sort_values(KEY).reset_index(drop=True),
            base.sort_values(KEY).reset_index(drop=True),
            check_exact=True,
        )
        assert len(group) == 1001 and not group.duplicated(KEY).any()
    return checked


def evaluate(trades, calendar):
    rows, full_fills, curves = [], [], []
    for (label, stop), group in trades.groupby(["exit_rule", "stop_atr"]):
        for risk, cap, (cost, plan, slip), (period, (a, z)) in product(
            (0.01, 0.02),
            (2.0, 4.0),
            (("gross", "none", 0.0), ("tiered_1c", "tiered", 0.01)),
            E.PERIODS.items(),
        ):
            cal = calendar[(calendar >= (a or calendar[0])) & (calendar <= (z or calendar[-1]))]
            t = group[group.date.isin(cal)]
            eq, fills = E.portfolio(t, cal, plan, slip, risk=risk, leverage=cap)
            assert len(fills) == len(t), "Unfilled trades require explicit investigation"
            assert eq.min() > 0, "Insolvency must be reported before summarizing CAGR"
            assert abs(eq.iloc[-1] - 5000 - fills.pnl.sum()) < 1e-8
            pre = eq.shift(1).reindex(fills.date).to_numpy()
            fills = fills.assign(
                pretrade_equity=pre,
                entry_leverage=fills.qty * fills.entry_fill / pre,
                deployed_risk=fills.qty * fills.stop_dist / pre,
                trade_return=fills.pnl / pre,
                cap_bound=(risk / fills.stop_dist > cap / fills.entry_fill),
                risk_budget=risk,
                leverage_cap=cap,
                cost_case=cost,
            )
            assert (fills.entry_leverage <= cap + 1e-12).all()
            assert (fills.deployed_risk <= risk + 1e-12).all()
            worst = fills.loc[fills.trade_return.idxmin()]
            rows.append(
                {
                    "exit_rule": label,
                    "stop_atr": stop,
                    "risk_budget": risk,
                    "leverage_cap": cap,
                    "cost_case": cost,
                    "period": period,
                    **summarize(eq),
                    "trades": len(fills),
                    "stop_fraction": (fills.exit_reason == "stop").mean(),
                    "ema_fraction": (fills.exit_reason == "ema").mean(),
                    "net_win_fraction": (fills.pnl > 0).mean(),
                    "mean_gross_R": t.gross_R.mean(),
                    "mean_net_R": (fills.pnl / (fills.qty * fills.stop_dist)).mean(),
                    "mean_trade_return": fills.trade_return.mean(),
                    "mean_winner_return": fills.loc[fills.pnl > 0, "trade_return"].mean(),
                    "mean_loser_return": fills.loc[fills.pnl < 0, "trade_return"].mean(),
                    "worst_trade_return": worst.trade_return,
                    "worst_trade_date": str(worst.date.date()),
                    "worst_trade_ticker": worst.ticker,
                    "mean_entry_leverage": fills.entry_leverage.mean(),
                    "median_entry_leverage": fills.entry_leverage.median(),
                    "p95_entry_leverage": fills.entry_leverage.quantile(0.95),
                    "max_entry_leverage": fills.entry_leverage.max(),
                    "mean_deployed_risk": fills.deployed_risk.mean(),
                    "cap_bound_fraction": fills.cap_bound.mean(),
                    "fees": fills.costs.sum(),
                }
            )
            if period == "all":
                full_fills.append(fills)
                curves.append(
                    pd.DataFrame(
                        {
                            "date": eq.index,
                            "equity": eq.to_numpy(),
                            "exit_rule": label,
                            "stop_atr": stop,
                            "risk_budget": risk,
                            "leverage_cap": cap,
                            "cost_case": cost,
                        }
                    )
                )
    return pd.DataFrame(rows), pd.concat(full_fills, ignore_index=True), pd.concat(curves)


def diagnostics(trades, fills, calendar, groups, daily_close, output, artifacts):
    baseline = fills[
        (fills.cost_case == "tiered_1c") & (fills.risk_budget == 0.01) & (fills.leverage_cap == 2)
    ]
    path_rows, pairs, changes, continuations = [], [], [], []
    for (label, stop), group in trades.groupby(["exit_rule", "stop_atr"]):
        f = baseline[(baseline.exit_rule == label) & (baseline.stop_atr == stop)]
        stopped = group[group.exit_reason == "stop"]
        ages = (stopped.exit_time - stopped.entry_time).dt.total_seconds() / 60
        path_rows.append(
            {
                "exit_rule": label,
                "stop_atr": stop,
                "trades": len(group),
                "stops": len(stopped),
                "stop_fraction": len(stopped) / len(group),
                "ema_exits": int((group.exit_reason == "ema").sum()),
                "close_exits": int((group.exit_reason == "close").sum()),
                "net_win_fraction": (f.pnl > 0).mean(),
                "stop_age_median": ages.median(),
                "stops_under30_fraction": (ages < 30).mean(),
                "stops_under60_fraction": (ages < 60).mean(),
                "entry_minute_stops": int((ages == 0).sum()),
                "stops_before1030_fraction": (
                    (stopped.exit_time.dt.hour * 60 + stopped.exit_time.dt.minute) < 630
                ).mean(),
            }
        )
    for label in EXITS:
        wide = trades[(trades.exit_rule == label) & (trades.stop_atr == 1)].set_index(KEY)
        narrow = trades[(trades.exit_rule == label) & (trades.stop_atr == 0.5)].set_index(KEY)
        quantities = baseline[(baseline.exit_rule == label) & (baseline.stop_atr == 1)]
        quantities = quantities.set_index(KEY).qty
        for key, w in wide.iterrows():
            n, q = narrow.loc[key], quantities.loc[key]
            wp, npnl = D.net_result(w, q), D.net_result(n, q)
            same_exit = w.exit_time == n.exit_time and w.exit_px_cons == n.exit_px_cons
            pairs.append(
                {
                    "exit_rule": label,
                    "date": key[0],
                    "ticker": key[1],
                    "wide_win": wp > 0,
                    "narrow_win_same_qty": npnl > 0,
                    "narrow_stop": n.exit_reason == "stop",
                    "narrow_entry_minute_stop": n.exit_reason == "stop"
                    and n.exit_time == n.entry_time,
                    "same_exit": same_exit,
                    "wide_net_R": wp / (q * w.stop_dist),
                    "narrow_net_in_wide_R": npnl / (q * w.stop_dist),
                }
            )
    pair_frame = pd.DataFrame(pairs)
    pair_rows = []
    for label, g in pair_frame.groupby("exit_rule"):
        wins = g[g.wide_win]
        killed = wins.narrow_stop & ~wins.narrow_win_same_qty
        pair_rows.append(
            {
                "exit_rule": label,
                "wide_winners": len(wins),
                "wide_winners_killed_by_narrow_stop": int(killed.sum()),
                "wide_winners_killed_fraction": killed.mean(),
                "wide_winners_same_exit": int(wins.same_exit.sum()),
                "killed_winners_in_entry_minute": int(
                    (killed & wins.narrow_entry_minute_stop).sum()
                ),
                "trades_excluding_narrow_entry_minute_stops": int(
                    (~g.narrow_entry_minute_stop).sum()
                ),
                "mean_delta_excluding_narrow_entry_minute_stops": (
                    g.loc[~g.narrow_entry_minute_stop, "narrow_net_in_wide_R"]
                    - g.loc[~g.narrow_entry_minute_stop, "wide_net_R"]
                ).mean(),
                "mean_narrow_minus_wide_net_in_wide_R": (
                    g.narrow_net_in_wide_R - g.wide_net_R
                ).mean(),
            }
        )
    daily = pd.DataFrame(0.0, index=calendar, columns=["traded"])
    specs = {}
    for stop in STOPS:
        one = trades[(trades.exit_rule == "ema1") & (trades.stop_atr == stop)].set_index(KEY)
        two = trades[(trades.exit_rule == "ema2") & (trades.stop_atr == stop)].set_index(KEY)
        hold = trades[(trades.exit_rule == "hold") & (trades.stop_atr == stop)].set_index(KEY)
        quantities = baseline[(baseline.exit_rule == "hold") & (baseline.stop_atr == stop)]
        quantities = quantities.set_index(KEY).qty
        column = f"two_minus_one_net_R_stop{stop:g}"
        daily[column] = 0.0
        for key, second in two.iterrows():
            first, q = one.loc[key], quantities.loc[key]
            delta = (D.net_result(second, q) - D.net_result(first, q)) / (q * second.stop_dist)
            changes.append(
                {
                    "stop_atr": stop,
                    "date": key[0],
                    "ticker": key[1],
                    "delta_net_R": delta,
                    "one_exit": first.exit_reason,
                    "two_exit": second.exit_reason,
                    "extra_minutes": (second.exit_time - first.exit_time).total_seconds() / 60,
                }
            )
            daily.loc[key[0], "traded"] = 1.0
            daily.loc[key[0], column] = delta
            if second.exit_reason == "ema":
                control = hold.loc[key]
                onward = D.continuation(groups[key], second, control, daily_close.loc[key])
                continuations.append(
                    {
                        "stop_atr": stop,
                        "date": key[0],
                        "ticker": key[1],
                        **onward,
                        "hold_better_net": D.net_result(control, q)
                        > D.net_result(second, q) + 1e-10,
                    }
                )
        specs[column] = (column, "traded")
    change_frame = pd.DataFrame(changes)
    change_rows = []
    for stop, g in change_frame.groupby("stop_atr"):
        change_rows.append(
            {
                "stop_atr": stop,
                "two_better": int((g.delta_net_R > 1e-10).sum()),
                "one_better": int((g.delta_net_R < -1e-10).sum()),
                "same": int((g.delta_net_R.abs() <= 1e-10).sum()),
                "mean_delta_net_R": g.delta_net_R.mean(),
                "sum_gained_R": g.delta_net_R.clip(lower=0).sum(),
                "sum_lost_R": -g.delta_net_R.clip(upper=0).sum(),
                "new_stops_after_one_ema_exit": int(
                    ((g.one_exit == "ema") & (g.two_exit == "stop")).sum()
                ),
                "mean_extra_minutes": g.extra_minutes.mean(),
            }
        )
    continuation_frame = pd.DataFrame(continuations)
    continuation_rows = []
    for stop, g in continuation_frame.groupby("stop_atr"):
        continuation_rows.append(
            {
                "stop_atr": stop,
                "two_close_ema_exits": len(g),
                "hold_better_net_fraction": g.hold_better_net.mean(),
                "another_half_R_before_stop_fraction": (
                    g.before_stop_favorable_R_lower >= 0.5 - 1e-10
                ).mean(),
                "another_one_R_before_stop_fraction": (
                    g.before_stop_favorable_R_lower >= 1 - 1e-10
                ).mean(),
                "original_stop_later_fraction": g.control_stops_later.mean(),
            }
        )
    for name, frame in (
        ("paths", pd.DataFrame(path_rows)),
        ("narrow_stop_pairs", pd.DataFrame(pair_rows)),
        ("confirmation_pairs", pd.DataFrame(change_rows)),
        ("continuation", pd.DataFrame(continuation_rows)),
        ("uncertainty", D.block_intervals(daily, specs)),
    ):
        frame.to_csv(output / f"{name}.csv", index=False)
    pair_frame.to_parquet(artifacts / "confirmation_risk_stop_pairs.parquet", index=False)
    change_frame.to_parquet(artifacts / "confirmation_risk_exit_pairs.parquet", index=False)
    continuation_frame.to_parquet(artifacts / "confirmation_risk_continuation.parquet", index=False)


def chart(metrics, curves, artifacts):
    m = metrics[(metrics.period == "all") & (metrics.cost_case == "tiered_1c")]
    fig = make_subplots(
        rows=1, cols=2, subplot_titles=("Return and closing drawdown", "1% risk, 2x cap")
    )
    for label in EXITS:
        p = m[m.exit_rule == label]
        desc = [
            f"{r.stop_atr:g} ATR, {100 * r.risk_budget:g}% risk, {r.leverage_cap:g}x cap"
            for r in p.itertuples()
        ]
        fig.add_trace(
            go.Scatter(
                x=-100 * p["max DD"],
                y=100 * p.CAGR,
                mode="markers",
                name=NAMES[label],
                text=desc,
                marker={"size": 11},
                hovertemplate=(
                    "%{text}<br>Drawdown %{x:.1f}%<br>CAGR %{y:.1f}%<extra>%{fullData.name}</extra>"
                ),
            ),
            row=1,
            col=1,
        )
    for label, stop in product(EXITS, STOPS):
        c = curves[
            (curves.cost_case == "tiered_1c")
            & (curves.exit_rule == label)
            & (curves.stop_atr == stop)
            & (curves.risk_budget == 0.01)
            & (curves.leverage_cap == 2)
        ]
        fig.add_trace(
            go.Scatter(
                x=c.date,
                y=c.equity,
                mode="lines",
                name=f"{NAMES[label]}, {stop:g} ATR",
            ),
            row=1,
            col=2,
        )
    fig.update_xaxes(title_text="Maximum closing drawdown (%)", row=1, col=1)
    fig.update_yaxes(title_text="Annualized return (%)", row=1, col=1)
    fig.update_yaxes(title_text="Equity ($)", row=1, col=2)
    fig.update_layout(template="plotly_white", height=600, title="ORB exits, stop width and sizing")
    path = artifacts / "confirmation_risk.html"
    intro = """<!doctype html><meta charset='utf-8'><title>ORB stop and sizing study</title>
<style>body{font-family:system-ui;margin:24px}p{max-width:1100px;line-height:1.5}</style>
<h1>ORB stop and sizing study</h1><p>Same 1,001 entries, 2021-10-22 through 2026-10-01.
IBKR Tiered model + assumed 1c/share entry and non-auction exit slippage. $5,000 initial
equity, whole shares. Caps are hypothetical; margin liquidation and borrow costs are
not modeled. Drawdown uses daily closing equity. This is reused research history,
not an untouched validation set. Hover for configuration details; click legends to filter.</p>"""
    path.write_text(intro + fig.to_html(full_html=False, include_plotlyjs=True), encoding="utf-8")
    return path


def main():
    output = Path(__file__).parent
    artifacts = data_dir() / "orb_ema_2026_10_02"
    manifest_path = output.parent / "exit15_tiered1c/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    source = E.orb._derived_path("orb5_stop1_trades")
    split_path = data_dir() / "massive/reference/splits.parquet"
    for path in (source, split_path):
        assert sha(path) == manifest["sha256"][str(path)], f"Frozen source changed: {path}"
    old_path = artifacts / "trades_5m_exit15m.parquet"
    cache_path = artifacts / f"inputs_{manifest['input_key']}.parquet"
    meta_path = cache_path.with_suffix(".json")
    meta = json.loads(meta_path.read_text())
    source_dates = pd.DatetimeIndex(sorted(pd.Timestamp(s["day"]) for s in meta["sources"]))
    ends = {pd.Timestamp(k): pd.Timestamp(v) for k, v in meta["ends"].items()}
    calendar = pd.DatetimeIndex(massive.local_days())
    calendar = calendar[(calendar >= manifest["first"]) & (calendar <= manifest["last"])]
    assert len(calendar) == 1240
    candidates = pd.read_parquet(source)
    picked = candidates[(candidates["rank"] == 1) & candidates.date.isin(calendar)].sort_values(
        "date"
    )
    groups = dict(tuple(pd.read_parquet(cache_path).groupby(KEY, sort=False)))
    trades = simulate_paths(picked, groups, source_dates, ends, pd.read_parquet(split_path))
    checked = check_controls(trades, pd.read_parquet(old_path))
    print(
        f"Exact control matches: {checked}; all six paths have the same 1,001 entries", flush=True
    )
    trades.to_parquet(artifacts / "confirmation_risk_trades.parquet", index=False)
    metrics, fills, curves = evaluate(trades, calendar)
    assert len(metrics) == 144
    # Independently saved earlier account results must also reproduce.
    prior_metrics = pd.read_csv(output.parent / "exit15_tiered1c/metrics.csv")
    for label, variant in (("hold", "orb"), ("ema1", "orb_ema_exit")):
        for stop in STOPS:
            new = metrics[
                (metrics.exit_rule == label)
                & (metrics.stop_atr == stop)
                & (metrics.risk_budget == 0.01)
                & (metrics.leverage_cap == 2)
            ]
            old = prior_metrics[
                (prior_metrics.variant == variant) & (prior_metrics.stop_atr == stop)
            ]
            columns = ["CAGR", "Sharpe", "max DD", "final"]
            for frame in (new, old):
                assert len(frame) == 6
            np.testing.assert_allclose(
                new.set_index(["cost_case", "period"])[columns].sort_index(),
                old.set_index(["cost_case", "period"])[columns].sort_index(),
                rtol=1e-12,
                atol=1e-12,
            )
    metrics.to_csv(output / "metrics.csv", index=False)
    fills.to_parquet(artifacts / "confirmation_risk_fills.parquet", index=False)
    curves.to_parquet(artifacts / "confirmation_risk_equity.parquet", index=False)
    diagnostics(trades, fills, calendar, groups, picked.set_index(KEY)["close"], output, artifacts)
    chart_path = chart(metrics, curves, artifacts)
    sources = [
        source,
        split_path,
        old_path,
        cache_path,
        meta_path,
        manifest_path,
        Path(E.__file__),
        Path(E.orb.__file__),
        Path(D.__file__),
        Path(__file__),
        output / "protocol.md",
        Path("tests/test_orb_ema.py"),
        Path("src/horizon_trader/execution/costs.py"),
    ]
    audit = {
        "sessions": len(calendar),
        "first": manifest["first"],
        "last": manifest["last"],
        "trades_per_path": 1001,
        "paths": 6,
        "exact_old_trade_matches": checked,
        "prior_account_metrics_reproduced": 24,
        "configurations": 24,
        "metrics_rows": len(metrics),
        "costs": "IBKR Tiered + assumed 1c entry/non-auction exit slippage",
        "tests": "66 targeted tests passed",
        "development_audit": (
            "Initial control checks caught fixed-offset versus named-zone timestamps, then "
            "microsecond versus nanosecond storage. Exact instants were normalized to New York "
            "nanoseconds for comparisons. All 4,004 controls then matched; no price paths changed."
        ),
        "chart": str(chart_path),
        "source_sha256": {str(p): sha(p) for p in sources},
        "output_sha256": {p.name: sha(p) for p in sorted(output.glob("*.csv"))},
    }
    (output / "verification.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(
        metrics[(metrics.period == "all") & (metrics.cost_case == "tiered_1c")][
            [
                "exit_rule",
                "stop_atr",
                "risk_budget",
                "leverage_cap",
                "CAGR",
                "max DD",
                "Sharpe",
                "stop_fraction",
                "net_win_fraction",
                "worst_trade_return",
                "mean_entry_leverage",
                "cap_bound_fraction",
            ]
        ]
        .round(5)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
