"""Post-trade diagnostics for the fixed ORB experiment, never trading signals."""

from __future__ import annotations

import numpy as np
import pandas as pd

from horizon_trader.intraday import orb


def net_result(trade, qty: float, slip=0.01) -> float:
    """Paired outcomes use identical share counts and actual modeled exit fees."""
    side = trade.side
    entry = trade.entry_px + side * slip
    exit_ = trade.exit_px_cons - side * slip * (trade.exit_reason != "close")
    cost = orb.trade_costs([qty], [entry], [exit_], [side], "tiered")[0]
    return float(side * qty * (exit_ - entry) - cost)


def favorable_extreme(bars: pd.DataFrame, side: int, fallback: float) -> float:
    """Price with the largest signed favorable movement; works for shorts too."""
    if bars.empty:
        return fallback
    return max(fallback, bars.high.max()) if side > 0 else min(fallback, bars.low.min())


def continuation(bars: pd.DataFrame, exited, control, close_px: float) -> dict:
    """Post-EMA excursions with and without retaining the original protective stop.

    `bars` must contain regular-session bars only. R is the original stop distance,
    and future excursions start at the EMA exit's raw fill. Stops are minute-bar
    events; their high/low cannot establish ordering within the stopping minute.
    """
    if exited.exit_reason != "ema":
        raise ValueError("Continuation requires an EMA exit")
    if control.exit_time < exited.exit_time:
        raise ValueError("Control cannot stop before the managed trade exits")
    side, px, dist = int(exited.side), exited.exit_px_cons, exited.stop_dist

    def best(*prices):
        return max(prices) if side > 0 else min(prices)

    later = bars[bars.ts >= exited.exit_time]
    entire = best(favorable_extreme(later, side, px), close_px)
    before = bars[(bars.ts >= exited.entry_time) & (bars.ts < exited.exit_time)]
    peak_before = favorable_extreme(before, side, best(px, exited.entry_px))
    if control.exit_reason == "stop":
        safe = later[later.ts < control.exit_time]
        stopping = later[later.ts == control.exit_time]
        if len(stopping) != 1:
            raise ValueError("Expected exactly one stopping minute")
        lower = favorable_extreme(safe, side, px)
        stop_open = float(stopping.open.iloc[0])
        lower = best(lower, stop_open)
        stop_px = exited.entry_px - side * dist
        gapped = side * (stop_open - stop_px) <= 0
        upper = lower if gapped else favorable_extreme(stopping, side, lower)
    else:
        lower = upper = entire
    return {
        "later_favorable_R": max(0.0, side * (entire - px) / dist),
        "before_stop_favorable_R_lower": max(0.0, side * (lower - px) / dist),
        "before_stop_favorable_R_upper": max(0.0, side * (upper - px) / dist),
        "later_new_extreme": bool(side * (entire - peak_before) > 1e-10),
        "before_stop_new_extreme_lower": bool(side * (lower - peak_before) > 1e-10),
        "before_stop_new_extreme_upper": bool(side * (upper - peak_before) > 1e-10),
        "control_stops_later": control.exit_reason == "stop",
        "control_minus_exit_gross_R": control.gross_R - exited.gross_R,
    }


def stop_recovery(bars: pd.DataFrame, trade, close_px: float) -> dict:
    """Descriptive post-stop recovery, excluding unknown within-stop-minute prices."""
    if trade.exit_reason != "stop":
        raise ValueError("Recovery requires a stopped trade")
    side, entry, dist = int(trade.side), trade.entry_px, trade.stop_dist
    later = bars[bars.ts > trade.exit_time]
    extreme = favorable_extreme(later, side, close_px)
    before = bars[(bars.ts >= trade.entry_time) & (bars.ts < trade.exit_time)]
    pre = favorable_extreme(before, side, entry)
    return {
        "later_reclaims_entry": bool(side * (extreme - entry) >= 0),
        "close_beyond_entry": bool(side * (close_px - entry) > 0),
        "hypothetical_unstopped_close_R": side * (close_px - entry) / dist,
        "unambiguous_pre_stop_mfe_R": max(0.0, side * (pre - entry) / dist),
    }


def stop_timing(trades: pd.DataFrame, label: str) -> pd.DataFrame:
    """Counts, denominator-aware timing and positions still at risk by trade age."""
    stopped = trades[trades.exit_reason == "stop"]
    elapsed = (stopped.exit_time - stopped.entry_time).dt.total_seconds() / 60
    duration = (trades.exit_time - trades.entry_time).dt.total_seconds() / 60
    clock = stopped.exit_time.dt.hour * 60 + stopped.exit_time.dt.minute
    axes = (
        (
            "elapsed",
            elapsed,
            [0, 5, 15, 30, 60, 120, np.inf],
            ["<5 min", "5-15 min", "15-30 min", "30-60 min", "60-120 min", "120+ min"],
        ),
        (
            "clock_ET",
            clock,
            [0, 600, 630, 660, 720, 840, np.inf],
            [
                "before 10:00",
                "10:00-10:30",
                "10:30-11:00",
                "11:00-12:00",
                "12:00-14:00",
                "14:00-close",
            ],
        ),
    )
    rows = []
    for axis, values, edges, labels in axes:
        for a, z, bucket in zip(edges[:-1], edges[1:], labels, strict=True):
            n = int(((values >= a) & (values < z)).sum())
            at_risk = int((duration >= a).sum()) if axis == "elapsed" else None
            rows.append(
                {
                    "strategy": label,
                    "axis": axis,
                    "bucket": bucket,
                    "stops": n,
                    "all_stops": len(stopped),
                    "all_trades": len(trades),
                    "fraction_of_stops": n / len(stopped) if len(stopped) else np.nan,
                    "fraction_of_trades": n / len(trades),
                    "at_risk_at_bin_start": at_risk,
                    "conditional_stop_fraction": n / at_risk if at_risk else np.nan,
                }
            )
    return pd.DataFrame(rows)


def block_intervals(daily: pd.DataFrame, specs: dict, samples=2000, block=21, seed=20261002):
    """Ratio-of-sums percentile intervals using paired circular calendar blocks."""
    rng = np.random.default_rng(seed)
    n = len(daily)
    if n < 2 * block:
        raise ValueError("Insufficient calendar for block resampling")
    starts = rng.integers(0, n, size=(samples, int(np.ceil(n / block))))
    idx = ((starts[:, :, None] + np.arange(block)) % n).reshape(samples, -1)[:, :n]
    rows = []
    for name, (numerator, denominator) in specs.items():
        num, den = daily[numerator].to_numpy(), daily[denominator].to_numpy()
        sums = den[idx].sum(axis=1)
        ratios = num[idx].sum(axis=1) / np.where(sums > 0, sums, np.nan)
        lo, hi = np.nanquantile(ratios, [0.025, 0.975])
        rows.append(
            {
                "statistic": name,
                "estimate": num.sum() / den.sum(),
                "ci95_low": lo,
                "ci95_high": hi,
                "samples": samples,
                "block_sessions": block,
            }
        )
    return pd.DataFrame(rows)
