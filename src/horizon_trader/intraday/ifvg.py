"""Mechanical IFVG signals and conservative minute-bar execution, with no broker calls.

Research runner: ``python -m horizon_trader.intraday.ifvg_study``.
Exact experiment: research/ifvg_2026_10_18/protocol.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor

import numpy as np
import pandas as pd

from horizon_trader.execution.costs import IBKR_PLANS, ZERO_COSTS

STRATEGIES = ("ifvg_close", "ifvg_retest", "breakout_close", "breakout_retest")
TZ = "America/New_York"
MINUTE = pd.Timedelta(minutes=1)


@dataclass(frozen=True)
class Rules:
    candle_minutes: int = 5
    min_gap: float = 0.02
    gap_age: int = 12
    retest_age: int = 6
    tick: float = 0.01
    first_minute: int = 15
    last_minute: int = 120

    def __post_init__(self):
        if self.candle_minutes < 1 or 390 % self.candle_minutes:
            raise ValueError("Candle length must be a positive divisor of 390")
        if not (self.min_gap > 0 and self.tick > 0 and self.gap_age > 0 and self.retest_age > 0):
            raise ValueError("Gap, tick and expiry settings must be positive")
        if not 0 <= self.first_minute <= self.last_minute < 210:
            raise ValueError("Entry window must precede even a half-day close")


DEFAULT_RULES = Rules()


def candles(minutes: pd.DataFrame, rules: Rules = DEFAULT_RULES) -> pd.DataFrame:
    """Complete session-aligned candles; availability is the end, never the start.

    A missing minute invalidates its candle. This function supports truncated
    input so causality can be checked independently of full-session data QC.
    """
    if minutes.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])
    b = minutes.sort_values("ts").copy()
    if b.ts.dt.tz is None or b.ts.duplicated().any():
        raise ValueError("Expected unique timezone-aware timestamps")
    b["ts"] = b.ts.dt.tz_convert(TZ)
    start = b.ts.dt.normalize() + pd.Timedelta(minutes=570)
    offset = (b.ts - start) / MINUTE
    if (offset % 1 != 0).any():
        raise ValueError("Expected minute-start timestamps")
    b = b[(offset >= 0) & (offset < 390)].copy()
    offset = offset.loc[b.index].astype(int)
    b["time"] = start.loc[b.index] + pd.to_timedelta(
        (offset // rules.candle_minutes + 1) * rules.candle_minutes, unit="min"
    )
    out = b.groupby("time", sort=True).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        count=("ts", "size"),
        last=("ts", "max"),
    )
    out = out[(out["count"] == rules.candle_minutes) & (out["last"] + MINUTE == out.index)]
    return out[["open", "high", "low", "close"]].reset_index()


def signals(bars: pd.DataFrame, strategy: str, rules: Rules = DEFAULT_RULES) -> list[dict]:
    """Return causal signals; the simulator accepts at most one valid entry per day."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}")
    if bars.empty:
        return []
    if bars.time.dt.normalize().nunique() != 1:
        raise ValueError("Signals must be generated one session at a time")
    rows = list(bars.itertuples(index=False))
    active, result = [], []
    pending = None
    interval = pd.Timedelta(minutes=rules.candle_minutes)
    start = rows[0].time.normalize() + pd.Timedelta(minutes=570)

    def emit(zone, time):
        result.append({**zone, "signal_time": time})

    for i, row in enumerate(rows):
        minute = (row.time - start) / MINUTE
        if minute > rules.last_minute:
            break
        inversions = []
        still_active = []
        for gap in active:
            if row.time - gap["formed_time"] > interval * rules.gap_age:
                continue
            inverted = row.close < gap["lower"] if gap["side"] == -1 else row.close > gap["upper"]
            if inverted:
                inversions.append({**gap, "inversion_time": row.time})
            else:
                still_active.append(gap)
        active = still_active

        candidate = inversions[-1] if inversions else None
        if strategy.startswith("breakout"):
            candidate = None
            if i >= 3 and row.time - rows[i - 3].time == 3 * interval:
                prior = rows[i - 3 : i]
                lower, upper = min(x.low for x in prior), max(x.high for x in prior)
                side = 1 if row.close > upper else -1 if row.close < lower else 0
                if side:
                    candidate = dict(
                        lower=lower,
                        upper=upper,
                        side=side,
                        formed_time=rows[i - 1].time,
                        inversion_time=row.time,
                    )

        if strategy.endswith("retest"):
            if pending is not None:
                side = pending["side"]
                invalid = (
                    row.close < pending["lower"] if side == 1 else row.close > pending["upper"]
                )
                expired = row.time - pending["inversion_time"] > interval * rules.retest_age
                if invalid or expired:
                    pending = None
                else:
                    touched = (
                        row.low <= pending["upper"] if side == 1 else row.high >= pending["lower"]
                    )
                    rejected = (
                        row.close > pending["upper"] if side == 1 else row.close < pending["lower"]
                    )
                    if touched and rejected:
                        emit(pending, row.time)
                        pending = None
            if pending is None and candidate is not None and minute >= rules.first_minute:
                pending = candidate
        elif candidate is not None and minute >= rules.first_minute:
            emit(candidate, row.time)

        # A zone only exists once all three candles have completed, and cannot
        # invert on its formation candle. Missing candles break the pattern.
        if i >= 2 and row.time - rows[i - 2].time == 2 * interval:
            first = rows[i - 2]
            if row.low - first.high >= rules.min_gap - 1e-10:
                active.append(dict(lower=first.high, upper=row.low, side=-1, formed_time=row.time))
            if first.low - row.high >= rules.min_gap - 1e-10:
                active.append(dict(lower=row.high, upper=first.low, side=1, formed_time=row.time))
    return result


def outward(price: float, side: int, tick: float) -> float:
    """Round upward for +1, downward for -1, avoiding binary-float cent drift."""
    units = price / tick
    return (ceil(units - 1e-9) if side > 0 else floor(units + 1e-9)) * tick


def exit_path(
    minutes: pd.DataFrame,
    entry_i: int,
    side: int,
    stop: float,
    target: float,
    exit_time: pd.Timestamp,
) -> dict | None:
    """Stop-first bounds for ambiguous OHLC, including the entry minute.

    Truncated input returns None if the position is still open, never a fabricated
    end-of-sample liquidation. Exit time for a barrier identifies its minute.
    """
    for r in minutes.iloc[entry_i:].itertuples(index=False):
        stop_at_open = side * (r.open - stop) <= 0
        target_at_open = side * (r.open - target) >= 0
        if stop_at_open:
            price, reason, ambiguous = r.open, "stop_gap", False
        elif target_at_open:
            price, reason, ambiguous = target, "target", False
        elif r.ts >= exit_time:
            price, reason, ambiguous = r.open, "session_end", False
        else:
            stop_hit = r.low <= stop if side == 1 else r.high >= stop
            target_hit = r.high >= target if side == 1 else r.low <= target
            if not stop_hit and not target_hit:
                continue
            price, reason, ambiguous = (
                (stop, "stop", bool(target_hit)) if stop_hit else (target, "target", False)
            )
        return dict(exit_time=r.ts, exit_px=float(price), exit_reason=reason, ambiguous=ambiguous)
    return None


def simulate_day(
    minutes: pd.DataFrame,
    decisions: list[dict],
    strategy: str,
    target_r: float,
    exit_time: pd.Timestamp,
    rules: Rules = DEFAULT_RULES,
) -> dict | None:
    if not np.isfinite(target_r) or target_r <= 0:
        raise ValueError("target_r must be positive")
    b = minutes.sort_values("ts").reset_index(drop=True)
    index = {t: i for i, t in enumerate(b.ts)}
    for signal in decisions:
        i = index.get(signal["signal_time"])
        if i is None or b.ts.iloc[i] >= exit_time:
            continue  # never fill a missing open using a later price
        side = signal["side"]
        stop = outward(
            signal["lower"] - rules.tick if side == 1 else signal["upper"] + rules.tick,
            -side,
            rules.tick,
        )
        entry = float(b.open.iloc[i])
        risk = side * (entry - stop)
        if risk <= 0:
            continue
        target = outward(entry + side * target_r * risk, side, rules.tick)
        exit_ = exit_path(b, i, side, stop, target, exit_time)
        if exit_ is None:
            return None  # a filled position remains open; no second entry
        return {
            **signal,
            **exit_,
            "date": b.ts.iloc[i].tz_localize(None).normalize(),
            "strategy": strategy,
            "target_r": target_r,
            "entry_time": b.ts.iloc[i],
            "entry_px": entry,
            "stop": stop,
            "stop_dist": risk,
            "target": target,
            "gross_R": side * (exit_["exit_px"] - entry) / risk,
        }
    return None


def account(
    trades: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    cost_case: str,
    capital: float = 5000,
    risk_fraction: float = 0.01,
    max_gross: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Independent one-instrument account; fees and stop allowance constrain size."""
    if cost_case not in ("gross", "net", "stress"):
        raise ValueError("Unknown cost case")
    if capital <= 0 or not 0 < risk_fraction <= 1 or not 0 < max_gross <= 1:
        raise ValueError("Require positive capital, risk <= 1, and unlevered gross <= 1")
    model = ZERO_COSTS if cost_case == "gross" else IBKR_PLANS["tiered"]
    slip = {"gross": 0.0, "net": 0.01, "stress": 0.03}[cost_case]
    paths = {} if trades.empty else {t.date: t for t in trades.itertuples(index=False)}
    if len(paths) != len(trades):
        raise ValueError("Only one trade per session per independent account")
    equity, fills, days = capital, [], []
    for date in calendar:
        before, skipped = equity, 0
        t = paths.get(date)
        if t is not None and equity > 0:
            entry_fill = t.entry_px + t.side * slip
            stop_fill = t.stop - t.side * slip
            loss_per_share = t.side * (entry_fill - stop_fill)
            quantity = floor(
                min(equity * risk_fraction / loss_per_share, equity * max_gross / entry_fill)
            )
            while quantity > 0:
                entry_fee = model.total(t.side * quantity, entry_fill)
                stop_fee = model.total(-t.side * quantity, stop_fill)
                if (
                    quantity * entry_fill + entry_fee <= equity * max_gross
                    and quantity * loss_per_share + entry_fee + stop_fee <= equity * risk_fraction
                ):
                    break
                quantity -= 1
            if quantity:
                exit_fill = t.exit_px - t.side * slip
                fees = entry_fee + model.total(-t.side * quantity, exit_fill)
                gross = quantity * t.side * (t.exit_px - t.entry_px)
                slippage = 2 * quantity * slip
                pnl = gross - slippage - fees
                equity += pnl
                fills.append(
                    {
                        **t._asdict(),
                        "qty": quantity,
                        "entry_fill": entry_fill,
                        "exit_fill": exit_fill,
                        "fees": fees,
                        "slippage": slippage,
                        "gross_pnl": gross,
                        "pnl": pnl,
                        "net_R": pnl / (quantity * t.stop_dist),
                        "equity_before": before,
                        "equity_after": equity,
                        "planned_loss": quantity * loss_per_share + entry_fee + stop_fee,
                    }
                )
            else:
                skipped = 1
        days.append(
            dict(
                date=date,
                equity=equity,
                pnl=equity - before,
                return_=equity / before - 1 if before else 0,
                skipped=skipped,
            )
        )
    return pd.DataFrame(days).rename(columns={"return_": "return"}), pd.DataFrame(fills)


def metrics(daily: pd.DataFrame, fills: pd.DataFrame, capital: float = 5000) -> dict:
    """Daily zero-hurdle Sharpe includes all flat sessions and the initial capital."""
    r = daily["return"]
    equity = np.r_[capital, daily.equity.to_numpy()]
    dd = equity / np.maximum.accumulate(equity) - 1
    years = max((daily.date.iloc[-1] - daily.date.iloc[0]).days + 1, 1) / 365.25
    pnl = fills.pnl if len(fills) else pd.Series(dtype=float)
    loss = -pnl[pnl < 0].sum()
    return dict(
        sessions=len(daily),
        trades=len(fills),
        final_equity=equity[-1],
        total_return=equity[-1] / capital - 1,
        cagr=(equity[-1] / capital) ** (1 / years) - 1,
        sharpe=float(r.mean() / r.std(ddof=1) * np.sqrt(252)) if r.std(ddof=1) > 0 else np.nan,
        max_drawdown=float(dd.min()),
        win_rate=float((pnl > 0).mean()) if len(pnl) else np.nan,
        profit_factor=float(pnl[pnl > 0].sum() / loss) if loss else np.nan,
        avg_pnl=float(pnl.mean()) if len(pnl) else np.nan,
        avg_gross_R=float(fills.gross_R.mean()) if len(fills) else np.nan,
        avg_net_R=float(fills.net_R.mean()) if len(fills) else np.nan,
        fees=float(fills.fees.sum()) if len(fills) else 0,
        slippage=float(fills.slippage.sum()) if len(fills) else 0,
        gross_pnl_same_positions=float(fills.gross_pnl.sum()) if len(fills) else 0,
        ambiguous=int(fills.ambiguous.sum()) if len(fills) else 0,
        skipped_zero_shares=int(daily.skipped.sum()),
    )
