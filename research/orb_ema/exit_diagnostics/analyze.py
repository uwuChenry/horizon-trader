"""Describe existing trade paths without selecting or changing any strategy rules."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from horizon_trader.config import data_dir
from horizon_trader.datasources import massive
from horizon_trader.intraday import orb_ema as E
from horizon_trader.intraday import orb_exit_diagnostics as D

NAMES = {"orb": "ORB hold", "ema5": "5-minute EMA exit", "ema15": "15-minute EMA exit"}


def charts(output, artifacts, methods, summary, continuation):
    mix = go.Figure()
    for reason, title, color in (
        ("stop", "Stop", "#d55e00"),
        ("ema", "EMA exit", "#0072b2"),
        ("close", "Close auction", "#009e73"),
    ):
        mix.add_bar(
            name=title,
            x=[NAMES[k] for k in methods],
            y=[100 * summary.loc[k, f"{reason}_fraction"] for k in methods],
            marker_color=color,
            text=[int(summary.loc[k, f"{reason}_count"]) for k in methods],
            textposition="inside",
        )
    mix.update_layout(
        title="Exit outcomes: same 1,001 entries, 1 ATR stop",
        barmode="stack",
        yaxis_title="Percent of trades",
        template="plotly_white",
    )
    timing = go.Figure()
    for key, t in methods.items():
        stopped = t[t.exit_reason == "stop"]
        age = np.sort((stopped.exit_time - stopped.entry_time).dt.total_seconds() / 60)
        timing.add_scatter(
            x=age,
            y=100 * np.arange(1, len(age) + 1) / len(age),
            name=NAMES[key],
            mode="lines",
            line_shape="hv",
        )
    timing.update_layout(
        title="When stops occur, conditional on a stop-out",
        xaxis_title="Minutes after entry",
        yaxis_title="Cumulative % of stops",
        template="plotly_white",
    )
    forward = go.Figure()
    fields = ["any_later_favorable", "before_stop_half_R_lower", "hold_better_net"]
    for key in ("ema5", "ema15"):
        row = continuation.loc[key]
        forward.add_bar(
            name=NAMES[key],
            x=[
                "Any favorable move later",
                "Another 0.5R before stop",
                "Holding finishes better (net)",
            ],
            y=[100 * row[f"{f}_fraction"] for f in fields],
        )
    forward.update_layout(
        title="After EMA exits: three different definitions of continuation",
        barmode="group",
        yaxis_title="Percent of EMA exits",
        template="plotly_white",
    )
    parts = [
        "<!doctype html><meta charset='utf-8'><title>ORB exit diagnostics</title>",
        "<style>body{font-family:system-ui;max-width:1100px;margin:32px auto;padding:0 20px}"
        "p{line-height:1.5;color:#333}</style><h1>ORB exit diagnostics</h1>",
        "<p>2021-10-22 to 2026-10-01. Same 1,001 ORB entries; 1 prior daily ATR stop. "
        "Tiered and assumed 1c entry/non-auction exit slippage. Charts describe reused "
        "history, not future probabilities. 'Before stop' uses conservative minute-bar "
        "ordering; the small ambiguity range is saved in the tables.</p>",
    ]
    for i, fig in enumerate((mix, timing, forward)):
        parts.append(fig.to_html(full_html=False, include_plotlyjs=(i == 0)))
    path = artifacts / "exit_diagnostics.html"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def main():
    output = Path(__file__).parent
    artifacts = data_dir() / "orb_ema_2026_10_02"
    paths = [artifacts / "trades_5m.parquet", artifacts / "trades_5m_exit15m.parquet"]
    old, new = (pd.read_parquet(p) for p in paths)
    base = new[(new.variant == "orb") & (new.stop_atr == 1)].copy()
    methods = {
        "orb": base,
        "ema5": old[(old.variant == "orb_ema_exit") & (old.stop_atr == 1)].copy(),
        "ema15": new[(new.variant == "orb_ema_exit") & (new.stop_atr == 1)].copy(),
    }
    base = base.set_index(["date", "ticker"], drop=False)
    manifest_path = output.parent / "exit15_tiered1c/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    cache_path = artifacts / f"inputs_{manifest['input_key']}.parquet"
    inputs = pd.read_parquet(cache_path)
    groups = dict(tuple(inputs.groupby(["date", "ticker"], sort=False)))
    original_path = E.orb._derived_path("orb5_stop1_trades")
    original = pd.read_parquet(original_path)
    daily_close = original[original["rank"] == 1].set_index(["date", "ticker"])["close"]
    calendar = pd.DatetimeIndex(massive.local_days())
    calendar = calendar[(calendar >= manifest["first"]) & (calendar <= manifest["last"])]
    _, base_fills = E.portfolio(methods["orb"], calendar, "tiered", 0.01)
    quantities = base_fills.set_index(["date", "ticker"]).qty
    assert len(base) == len(base_fills) == 1001 and len(calendar) == 1240
    daily = pd.DataFrame(0.0, index=calendar, columns=["traded"])
    daily.loc[methods["orb"].date, "traded"] = 1
    observations, summaries, timings, recoveries, subgroup = [], [], [], [], []
    for label, trades in methods.items():
        assert len(trades) == len(base)
        _, fills = E.portfolio(trades, calendar, "tiered", 0.01)
        assert len(fills) == len(trades)
        stopped = trades[trades.exit_reason == "stop"]
        stop_age = (stopped.exit_time - stopped.entry_time).dt.total_seconds() / 60
        gross = trades.gross_R
        wins, losses = gross[gross > 0], gross[gross < 0]
        top_n = int(np.ceil(len(gross) * 0.05))
        row = {
            "strategy": label,
            "trades": len(trades),
            "gross_win_fraction": float((gross > 0).mean()),
            "net_win_fraction": float((fills.pnl > 0).mean()),
            "avg_gross_win_R": wins.mean(),
            "avg_gross_loss_R": losses.mean(),
            "mean_gross_R": gross.mean(),
            "median_gross_R": gross.median(),
            "gross_profit_factor_R": wins.sum() / -losses.sum(),
            "net_profit_factor_dollars": fills.pnl.clip(lower=0).sum()
            / -fills.pnl.clip(upper=0).sum(),
            "net_mean_R": (fills.pnl / (fills.qty * fills.stop_dist)).mean(),
            "stop_age_median": stop_age.median(),
            "stop_age_q25": stop_age.quantile(0.25),
            "stop_age_q75": stop_age.quantile(0.75),
            "stop_under_30_count": int((stop_age < 30).sum()),
            "stop_under_60_count": int((stop_age < 60).sum()),
            "stop_entry_minute_count": int((stop_age == 0).sum()),
            "top5pct_count": top_n,
            "top5pct_gross_R": gross.nlargest(top_n).sum(),
            "total_gross_R": gross.sum(),
            "top5pct_fraction_positive_R": gross.nlargest(top_n).sum() / wins.sum(),
        }
        for reason in ("stop", "ema", "close"):
            row[f"{reason}_count"] = int((trades.exit_reason == reason).sum())
            row[f"{reason}_fraction"] = row[f"{reason}_count"] / len(trades)
        summaries.append(row)
        timings.append(D.stop_timing(trades, label))
        daily[f"stop_{label}"] = 0.0
        daily.loc[stopped.date, f"stop_{label}"] = 1
        daily[f"net_R_{label}"] = 0.0
        for trade in trades.itertuples():
            key = (trade.date, trade.ticker)
            control = base.loc[key]
            assert trade.entry_time == control.entry_time and trade.entry_px == control.entry_px
            qty = quantities.loc[key]
            managed_pnl = D.net_result(trade, qty)
            control_pnl = D.net_result(control, qty)
            daily.loc[trade.date, f"net_R_{label}"] = managed_pnl / (qty * trade.stop_dist)
            if trade.exit_reason == "ema":
                post = D.continuation(groups[key], trade, control, daily_close.loc[key])
                post |= {
                    "strategy": label,
                    "date": trade.date,
                    "ticker": trade.ticker,
                    "side": trade.side,
                    "exit_time": trade.exit_time,
                    "exit_gross_R": trade.gross_R,
                    "exit_net_profit": managed_pnl > 0,
                    "exit_net_R": managed_pnl / (qty * trade.stop_dist),
                    "control_minus_exit_net_R": (control_pnl - managed_pnl)
                    / (qty * trade.stop_dist),
                }
                observations.append(post)
            if label == "orb" and trade.exit_reason == "stop":
                recoveries.append(
                    {
                        "date": trade.date,
                        "ticker": trade.ticker,
                        **D.stop_recovery(groups[key], trade, daily_close.loc[key]),
                    }
                )
        for period, a, z in (
            ("2021-23", "2021-01-01", "2023-12-31"),
            ("2024+", "2024-01-01", "2026-12-31"),
        ):
            part = fills[(fills.date >= a) & (fills.date <= z)]
            subgroup.append(
                {
                    "strategy": label,
                    "group": period,
                    "trades": len(part),
                    "stop_fraction": (part.exit_reason == "stop").mean(),
                    "net_win_fraction": (part.pnl > 0).mean(),
                    "net_mean_R": (part.pnl / (part.qty * part.stop_dist)).mean(),
                }
            )
        for side in (-1, 1):
            part = fills[fills.side == side]
            subgroup.append(
                {
                    "strategy": label,
                    "group": "long" if side > 0 else "short",
                    "trades": len(part),
                    "stop_fraction": (part.exit_reason == "stop").mean(),
                    "net_win_fraction": (part.pnl > 0).mean(),
                    "net_mean_R": (part.pnl / (part.qty * part.stop_dist)).mean(),
                }
            )
    obs = pd.DataFrame(observations)
    continuations, specs = [], {}
    for label in methods:
        specs[f"stop_rate_{label}"] = (f"stop_{label}", "traded")
        specs[f"mean_net_R_{label}"] = (f"net_R_{label}", "traded")
    for label in ("ema5", "ema15"):
        group = obs[obs.strategy == label].copy()
        flags = {
            "any_later_favorable": group.later_favorable_R > 1e-10,
            "new_extreme_later": group.later_new_extreme,
            "hold_better_gross": group.control_minus_exit_gross_R > 1e-10,
            "hold_better_net": group.control_minus_exit_net_R > 1e-10,
            "exit_better_net": group.control_minus_exit_net_R < -1e-10,
            "exit_profitable_net": group.exit_net_profit,
            "control_stops_later": group.control_stops_later,
            "before_stop_new_extreme_lower": group.before_stop_new_extreme_lower,
            "before_stop_new_extreme_upper": group.before_stop_new_extreme_upper,
        }
        for threshold, name in ((0.25, "quarter"), (0.5, "half"), (1, "one")):
            flags[f"later_{name}_R"] = group.later_favorable_R >= threshold - 1e-10
            for bound in ("lower", "upper"):
                flags[f"before_stop_{name}_R_{bound}"] = (
                    group[f"before_stop_favorable_R_{bound}"] >= threshold - 1e-10
                )
        row = {
            "strategy": label,
            "ema_exits": len(group),
            "mean_hold_minus_exit_net_R": group.control_minus_exit_net_R.mean(),
            "sum_gain_R_when_hold_better": group.control_minus_exit_net_R.clip(lower=0).sum(),
            "sum_saved_R_when_exit_better": -group.control_minus_exit_net_R.clip(upper=0).sum(),
            "median_later_favorable_R": group.later_favorable_R.median(),
        }
        daily[f"ema_{label}"] = 0.0
        daily.loc[group.date, f"ema_{label}"] = 1
        for flag, values in flags.items():
            row[f"{flag}_count"] = int(values.sum())
            row[f"{flag}_fraction"] = values.mean()
            daily[f"{flag}_{label}"] = 0.0
            daily.loc[group.date, f"{flag}_{label}"] = values.astype(float).to_numpy()
        specs[f"hold_better_net_{label}"] = (f"hold_better_net_{label}", f"ema_{label}")
        specs[f"half_R_before_stop_{label}"] = (f"before_stop_half_R_lower_{label}", f"ema_{label}")
        daily[f"net_delta_{label}"] = daily[f"net_R_{label}"] - daily.net_R_orb
        specs[f"paired_mean_net_R_change_{label}"] = (f"net_delta_{label}", "traded")
        continuations.append(row)
    summary = pd.DataFrame(summaries).set_index("strategy")
    onward = pd.DataFrame(continuations).set_index("strategy")
    recovery = pd.DataFrame(recoveries)
    summary.to_csv(output / "exit_summary.csv")
    onward.to_csv(output / "continuation_summary.csv")
    pd.concat(timings).to_csv(output / "stop_timing.csv", index=False)
    pd.DataFrame(subgroup).to_csv(output / "subgroups.csv", index=False)
    intervals = D.block_intervals(daily, specs)
    intervals.to_csv(output / "uncertainty.csv", index=False)
    recovery_summary = {
        "stops": len(recovery),
        "later_reclaims_entry": int(recovery.later_reclaims_entry.sum()),
        "close_beyond_entry": int(recovery.close_beyond_entry.sum()),
        "pre_stop_at_least_half_R": int((recovery.unambiguous_pre_stop_mfe_R >= 0.5).sum()),
        "pre_stop_at_least_one_R": int((recovery.unambiguous_pre_stop_mfe_R >= 1).sum()),
        "unstopped_close_R_quantiles": recovery.hypothetical_unstopped_close_R.quantile(
            [0, 0.1, 0.5, 0.9, 1]
        ).to_dict(),
    }
    (output / "stop_recovery.json").write_text(json.dumps(recovery_summary, indent=2))
    obs.to_parquet(artifacts / "exit_diagnostics_continuation.parquet", index=False)
    recovery.to_parquet(artifacts / "exit_diagnostics_stop_recovery.parquet", index=False)
    chart = charts(output, artifacts, methods, summary, onward)
    sources = [
        *paths,
        cache_path,
        original_path,
        Path(D.__file__),
        Path(E.__file__),
        Path(__file__),
        output / "protocol.md",
        Path("tests/test_orb_exit_diagnostics.py"),
    ]
    audit = {
        "sessions": len(calendar),
        "matched_trades_per_strategy": len(base),
        "ema_exits_analyzed": len(obs),
        "stop_recoveries_analyzed": len(recovery),
        "costs": "IBKR Tiered + assumed 1c entry/non-auction exit slippage",
        "tests": "56 targeted tests passed",
        "chart": str(chart),
        "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    }
    (output / "verification.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(
        summary[
            [
                "trades",
                "stop_count",
                "ema_count",
                "close_count",
                "net_win_fraction",
                "stop_age_median",
                "stop_under_30_count",
                "stop_under_60_count",
            ]
        ]
        .round(4)
        .to_string()
    )
    print(
        onward[
            [
                "ema_exits",
                "hold_better_net_fraction",
                "before_stop_half_R_lower_fraction",
                "before_stop_half_R_upper_fraction",
                "later_half_R_fraction",
                "control_stops_later_fraction",
                "sum_gain_R_when_hold_better",
                "sum_saved_R_when_exit_better",
            ]
        ]
        .round(4)
        .to_string()
    )
    print(json.dumps(recovery_summary, indent=2))


if __name__ == "__main__":
    main()
