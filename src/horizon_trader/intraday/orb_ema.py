"""Bounded ORB + EMA experiment. See research/orb_ema_2026_10_02/protocol.md.

    python -m horizon_trader.intraday.orb_ema

Only reads local market files. Saves reports and research artifacts; no broker calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.backtest.metrics import summarize
from horizon_trader.config import data_dir
from horizon_trader.datasources import massive
from horizon_trader.intraday import features as F
from horizon_trader.intraday import orb

VARIANTS = ("orb", "orb_ema_exit", "orb_ema_confirm", "selected_ema")
STOPS = (0.5, 0.75, 1.0, 1.5, 2.0)
PERIODS = {"all": (None, None), "2021-23": (None, "2023-12-31"), "2024+": ("2024-01-01", None)}
COLS = ["ts", "ticker", "open", "high", "low", "close"]


@dataclass(frozen=True)
class Rules:
    candle_minutes: int = 5
    exit_candle_minutes: int | None = None
    exit_confirmations: int = 1
    ema_span: int = 12
    opening_minutes: int = 5
    warmup_sessions: int = 5

    def __post_init__(self):
        if self.candle_minutes not in (1, 5, 15):
            raise ValueError("candle_minutes must be 1, 5 or 15")
        if self.exit_candle_minutes not in (None, 1, 5, 15):
            raise ValueError("exit_candle_minutes must be 1, 5, 15 or None")
        if self.exit_confirmations not in (1, 2):
            raise ValueError("exit_confirmations must be 1 or 2")
        if self.ema_span < 2 or self.warmup_sessions < 1:
            raise ValueError("EMA needs a positive warmup and span >= 2")


DEFAULT_RULES = Rules()


def session_end(spy: pd.DataFrame, day: pd.Timestamp) -> pd.Timestamp:
    """Infer the existing research calendar's half-day proxy from liquid SPY bars."""
    start = F.session_open(day.date())
    regular = spy[(spy.ts >= start) & (spy.ts < start + orb.CLOSE_TIME)]
    if regular.empty:
        raise ValueError(f"No SPY session on {day.date()}")
    last = (regular.ts.max() - start).total_seconds() / 60
    if last >= 389:
        return start + orb.CLOSE_TIME
    if 209 <= last <= 211:
        return start + pd.Timedelta(minutes=210)
    raise ValueError(f"Unrecognized SPY session on {day.date()}: last minute {last}")


def ema_signals(history: pd.DataFrame, today: pd.DataFrame, rules: Rules) -> pd.DataFrame:
    """Completed candles with availability timestamps; history is on today's split basis.

    A truncated final candle produces no signal. Missing end-minute candles are
    discarded rather than filled with a future or stale close.
    """
    both = pd.concat([history[["ts", "close"]], today[["ts", "close"]]])
    both = both.sort_values("ts").drop_duplicates("ts")
    block = rules.candle_minutes
    offset = both.ts.dt.hour * 60 + both.ts.dt.minute - 570
    both = both.assign(
        bucket=both.ts.dt.normalize()
        + pd.to_timedelta(570 + (offset // block + 1) * block, unit="min")
    )
    last = both.groupby("bucket", sort=True).tail(1).copy()
    last = last[last.ts + pd.Timedelta(minutes=1) == last.bucket]
    last["ema"] = last.close.ewm(
        span=rules.ema_span, adjust=False, min_periods=rules.ema_span
    ).mean()
    return last.rename(columns={"bucket": "signal_time"})[
        ["signal_time", "close", "ema"]
    ].reset_index(drop=True)


def adjust_history(history: pd.DataFrame, day: pd.Timestamp, splits: pd.DataFrame):
    """Only splits effective after a historical bar and on/before the decision day."""
    out = history.copy()
    for ev in splits.itertuples():
        effective = pd.Timestamp(ev.execution_date).normalize()
        if effective <= day and ev.split_from > 0 and ev.split_to > 0:
            before = out.ts.dt.tz_localize(None).dt.normalize() < effective
            out.loc[before, "close"] *= ev.split_from / ev.split_to
    return out


def simulate(
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    candidate: dict,
    variant: str,
    stop_atr: float,
    close_time: pd.Timestamp,
    rules: Rules = DEFAULT_RULES,
    exit_signals: pd.DataFrame | None = None,
) -> dict | None:
    """One causal round trip. EMA signals are known before their fill minute's range."""
    if variant not in VARIANTS or not np.isfinite(stop_atr) or stop_atr <= 0:
        raise ValueError("Unknown variant or invalid stop")
    day = pd.Timestamp(candidate["date"])
    start = F.session_open(day.date())
    cutoff = start + pd.Timedelta(minutes=rules.opening_minutes)
    b = bars[(bars.ts >= start) & (bars.ts < close_time)].sort_values("ts").reset_index(drop=True)
    opening = b[b.ts < cutoff]
    if opening.empty or opening.ts.iloc[0] != start:
        return None
    hi, lo = opening.high.max(), opening.low.min()

    def eligible(frame):
        if not frame.empty:
            frame = frame[(frame.signal_time >= cutoff) & (frame.signal_time < close_time)]
        return list(frame.dropna(subset=["close", "ema"]).itertuples(index=False))

    sig = eligible(signals)
    exits = eligible(signals if exit_signals is None else exit_signals)
    pending = pending_exit = 0
    latest = None
    prior_exit_time = None
    adverse_closes = 0
    exit_pending = False
    exit_interval = pd.Timedelta(minutes=rules.exit_candle_minutes or rules.candle_minutes)
    side = 0
    entry = None
    entry_i = None
    entry_time = None
    stop_dist = float(candidate["atr"]) * stop_atr
    if not np.isfinite(stop_dist) or stop_dist <= 0:
        return None

    def finish(px, idx, reason):
        return {
            "date": day,
            "ticker": candidate["ticker"],
            "rank": 1,
            "triggered": True,
            "variant": variant,
            "stop_atr": stop_atr,
            "side": side,
            "entry_px": entry,
            "entry_idx": entry_i,
            "entry_time": entry_time,
            "stop_dist": stop_dist,
            "exit_px_cons": float(px),
            "exit_idx_cons": idx,
            "stopped_cons": reason == "stop",
            "exit_reason": reason,
            "exit_time": b.ts.iloc[idx] if idx < len(b) else close_time,
            "gross_R": side * (px - entry) / stop_dist,
        }

    for i, row in enumerate(b.itertuples()):
        if row.ts < cutoff:
            continue
        new_signal = False
        while pending < len(sig) and sig[pending].signal_time <= row.ts:
            latest = sig[pending]
            pending += 1
            new_signal = True
        while pending_exit < len(exits) and exits[pending_exit].signal_time <= row.ts:
            latest_exit = exits[pending_exit]
            pending_exit += 1
            if entry is not None and latest_exit.signal_time > entry_time:
                if (
                    prior_exit_time is not None
                    and latest_exit.signal_time - prior_exit_time != exit_interval
                ):
                    adverse_closes = 0
                adverse_closes = (
                    adverse_closes + 1 if side * (latest_exit.close - latest_exit.ema) < 0 else 0
                )
                prior_exit_time = latest_exit.signal_time
                if adverse_closes >= rules.exit_confirmations:
                    exit_pending = True
        if entry is None:
            if variant in ("orb", "orb_ema_exit"):
                side = int(candidate["side"])
                level = hi if side > 0 else lo
                hit = row.high >= level if side > 0 else row.low <= level
                if not hit:
                    continue
                entry = max(row.open, level) if side > 0 else min(row.open, level)
            else:
                if not new_signal:
                    continue
                side = int(np.sign(latest.close - latest.ema))
                confirmed = latest.close > hi if side > 0 else latest.close < lo
                if side == 0 or (variant == "orb_ema_confirm" and not confirmed):
                    continue
                entry = row.open
            entry_i, entry_time = i, row.ts
        else:
            stop = entry - side * stop_dist
            if side * (row.open - stop) <= 0:
                return finish(row.open, i, "stop")
            if variant != "orb" and exit_pending:
                return finish(row.open, i, "ema")
        stop = entry - side * stop_dist
        adverse = row.low if side > 0 else row.high
        if side * (adverse - stop) <= 0:
            return finish(stop, i, "stop")
    if entry is not None:
        return finish(candidate["close"], len(b), "close")
    return None


def portfolio(trades, calendar, plan, slip, *, equity=5000.0, risk=0.01, leverage=2.0):
    """The shared ORB cost engine charges stop exits; explicitly charge EMA exits too."""
    if not all(np.isfinite(x) and x > 0 for x in (equity, risk, leverage)) or risk > 1:
        raise ValueError("Positive finite equity/leverage and risk in (0, 1] required")
    if trades.empty:
        index = pd.DatetimeIndex([calendar[0] - pd.Timedelta(days=1), *calendar])
        return pd.Series(float(equity), index=index, name="equity"), pd.DataFrame()
    adjusted = trades.copy()
    early = adjusted.exit_reason == "ema"
    adjusted.loc[early, "exit_px_cons"] -= adjusted.loc[early, "side"] * slip
    account = orb.Account(
        equity=equity,
        top_n=1,
        risk=risk,
        leverage=leverage,
        plan=plan,
        slippage=slip,
        same_bar="cons",
    )
    return orb.run_portfolio(adjusted, account, calendar)


def _read_job(job):
    day, tickers = job
    start = F.session_open(day.date())
    frame = pd.read_parquet(
        massive.local_path("minute", day.date()),
        columns=COLS,
        filters=[
            ("ticker", "in", sorted(tickers)),
            ("ts", ">=", start),
            ("ts", "<", start + orb.CLOSE_TIME),
        ],
    )
    end = session_end(frame[frame.ticker == "SPY"], day)
    return frame[frame.ts < end].assign(date=day), (day, end)


def load_inputs(picked, rules, artifact_dir):
    """Read each needed local day once for all candidate/warmup symbols; cache by inputs."""
    dates = pd.DatetimeIndex(massive.local_days())
    jobs = {}
    history_dates = {}
    for r in picked.itertuples():
        pos = dates.get_loc(r.date)
        days = dates[max(0, pos - rules.warmup_sessions) : pos + 1]
        history_dates[r.date] = days[:-1]
        for d in days:
            jobs.setdefault(d, {"SPY"}).add(r.ticker)
    signature = [
        {
            "day": str(d.date()),
            "tickers": sorted(t),
            "size": massive.local_path("minute", d.date()).stat().st_size,
            "mtime": massive.local_path("minute", d.date()).stat().st_mtime_ns,
        }
        for d, t in sorted(jobs.items())
    ]
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    cache = artifact_dir / f"inputs_{key}.parquet"
    meta = artifact_dir / f"inputs_{key}.json"
    if cache.exists() and meta.exists():
        frame = pd.read_parquet(cache)
        ends = {
            pd.Timestamp(k): pd.Timestamp(v)
            for k, v in json.loads(meta.read_text())["ends"].items()
        }
    else:
        frames, ends = [], {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            for i, (frame, (day, end)) in enumerate(pool.map(_read_job, sorted(jobs.items())), 1):
                frames.append(frame)
                ends[day] = end
                if i % 100 == 0 or i == len(jobs):
                    print(f"local session inputs: {i}/{len(jobs)}", flush=True)
        frame = pd.concat(frames, ignore_index=True)
        frame.to_parquet(cache, index=False)
        meta.write_text(
            json.dumps(
                {
                    "sources": signature,
                    "ends": {str(d.date()): t.isoformat() for d, t in ends.items()},
                },
                indent=2,
            )
        )
    groups = {(d, t): g for (d, t), g in frame.groupby(["date", "ticker"], sort=False)}
    return groups, history_dates, ends, key


def evaluate(trades, calendar, cost_cases):
    """Reprice raw round trips without changing the signal or the full calendar."""
    stats = []
    for (variant, stop), group in trades.groupby(["variant", "stop_atr"]):
        for label, plan, slip in cost_cases:
            for period, (a, z) in PERIODS.items():
                cal = calendar[(calendar >= (a or calendar[0])) & (calendar <= (z or calendar[-1]))]
                t = group[group.date.isin(cal)]
                eq, fills = portfolio(t, cal, plan, slip)
                result = {
                    "variant": variant,
                    "stop_atr": stop,
                    "cost_case": label,
                    "period": period,
                    **summarize(eq),
                    "trades": len(fills),
                    "mean_gross_R": t.gross_R.mean(),
                    "ema_exit_fraction": (t.exit_reason == "ema").mean(),
                    "stop_fraction": (t.exit_reason == "stop").mean(),
                    "fees": fills.costs.sum() if len(fills) else 0,
                }
                stats.append(result)
    return pd.DataFrame(stats)


def run(rules: Rules, output: Path, plan="tiered", slippage=0.01, legacy_costs=False):
    if plan not in ("fixed", "tiered") or not np.isfinite(slippage) or slippage < 0:
        raise ValueError("Expected Fixed/Tiered and finite, nonnegative slippage in dollars")
    output.mkdir(parents=True, exist_ok=True)
    artifacts = data_dir() / "orb_ema_2026_10_02"
    artifacts.mkdir(parents=True, exist_ok=True)
    source = orb._derived_path("orb5_stop1_trades")
    candidates = pd.read_parquet(source)
    picked = candidates[candidates["rank"] == 1].sort_values("date")
    calendar = pd.DatetimeIndex(massive.local_days())
    calendar = calendar[(calendar >= candidates.date.min()) & (calendar <= candidates.date.max())]
    splits_path = data_dir() / "massive/reference/splits.parquet"
    splits = pd.read_parquet(splits_path)
    groups, prior, ends, key = load_inputs(picked, rules, artifacts)
    rows, skipped = [], []
    empty = pd.DataFrame(columns=COLS)
    for number, candidate in enumerate(picked.to_dict("records"), 1):
        day, ticker = candidate["date"], candidate["ticker"]
        today = groups.get((day, ticker), empty)
        history = pd.concat([groups.get((d, ticker), empty) for d in prior[day]], ignore_index=True)
        if today.empty or history.empty:
            skipped.append({"date": day, "ticker": ticker, "reason": "missing bars/warmup"})
            continue
        history = adjust_history(history, day, splits[splits.ticker == ticker])
        signals = ema_signals(history, today, rules)
        exit_minutes = rules.exit_candle_minutes or rules.candle_minutes
        exit_signals = (
            signals
            if exit_minutes == rules.candle_minutes
            else ema_signals(history, today, replace(rules, candle_minutes=exit_minutes))
        )
        before = signals[signals.signal_time <= F.session_open(day.date())]
        exit_before = exit_signals[exit_signals.signal_time <= F.session_open(day.date())]
        if before.ema.notna().sum() == 0 or exit_before.ema.notna().sum() == 0:
            skipped.append({"date": day, "ticker": ticker, "reason": "insufficient EMA warmup"})
            continue
        for variant in VARIANTS:
            for stop in STOPS:
                trade = simulate(
                    today, signals, candidate, variant, stop, ends[day], rules, exit_signals
                )
                if trade is not None:
                    rows.append(trade)
        if number % 250 == 0:
            print(f"simulated {number}/{len(picked)} selected sessions", flush=True)
    trades = pd.DataFrame(rows)
    if skipped:
        calendar = calendar.difference(pd.DatetimeIndex([r["date"] for r in skipped]))
    cost_cases = [("gross", "none", 0.0), (f"{plan}_{100 * slippage:g}c", plan, slippage)]
    if legacy_costs:
        cost_cases = [
            ("gross", "none", 0.0),
            ("fixed_5c", "fixed", 0.05),
            ("tiered_5c", "tiered", 0.05),
        ]
    metrics = evaluate(trades, calendar, cost_cases)
    metrics.to_csv(output / "metrics.csv", index=False)
    exit_minutes = rules.exit_candle_minutes or rules.candle_minutes
    confirm_tag = f"_confirm{rules.exit_confirmations}" if rules.exit_confirmations > 1 else ""
    trade_path = (
        artifacts / f"trades_{rules.candle_minutes}m_exit{exit_minutes}m{confirm_tag}.parquet"
    )
    trades.to_parquet(trade_path, index=False)
    pd.DataFrame(skipped, columns=["date", "ticker", "reason"]).to_csv(
        output / "skipped.csv", index=False
    )
    manifest = {
        "rules": vars(rules),
        "cost_cases": cost_cases,
        "trades_path": str(trade_path),
        "input_key": key,
        "sessions": len(calendar),
        "first": str(calendar[0].date()),
        "last": str(calendar[-1].date()),
        "skipped": len(skipped),
        "signal_trials": len(VARIANTS) * len(STOPS),
        "sha256": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (source, splits_path, Path(__file__), output / "protocol.md")
            if p.exists()
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    headline = metrics[(metrics.stop_atr == 1) & (metrics.period == "all")]
    print(
        headline[["variant", "cost_case", "CAGR", "Sharpe", "max DD", "trades"]]
        .round(4)
        .to_string(index=False)
    )
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candle-minutes", type=int, choices=(1, 5, 15), default=5)
    parser.add_argument("--exit-candle-minutes", type=int, choices=(1, 5, 15), default=15)
    parser.add_argument("--exit-confirmations", type=int, choices=(1, 2), default=1)
    parser.add_argument("--plan", choices=("fixed", "tiered"), default="tiered")
    parser.add_argument("--slippage", type=float, default=0.01, help="Dollars per share per fill")
    parser.add_argument(
        "--legacy-costs", action="store_true", help="Reproduce the original cost grid"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Report directory; default name includes exit interval, costs and confirmation",
    )
    args = parser.parse_args()
    suffix = f"_confirm{args.exit_confirmations}" if args.exit_confirmations > 1 else ""
    output = args.output or Path("research/orb_ema_2026_10_02") / (
        f"exit{args.exit_candle_minutes}_{args.plan}{100 * args.slippage:g}c{suffix}"
    )
    run(
        Rules(
            candle_minutes=args.candle_minutes,
            exit_candle_minutes=args.exit_candle_minutes,
            exit_confirmations=args.exit_confirmations,
        ),
        output,
        args.plan,
        args.slippage,
        args.legacy_costs,
    )


if __name__ == "__main__":
    main()
