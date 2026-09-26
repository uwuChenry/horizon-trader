"""Pre-registered tests of ORB variations (written down before any of them was run).

    uv run python -m horizon_trader.intraday.orb_ideas [--save]

Baseline (the most realistic setup so far): top-1 stock by relative volume, stop 1 ATR from
the fill, stop-limit entry at the trigger price (filled at the limit, from 1-second bars),
stop-market stop-outs with the measured mean slippage, exit at the close. $5k IBKR Pro Tiered.

Ideas, each with its reason (15 variants in total, counted so the multiple-testing risk is
visible):
  market     Trade only in the direction of SPY's first 5-minute candle: a breakout against
             the index fights the broad order flow.                               (1 variant)
  cutoff     No entries after 10:00 / 10:30 / 11:00: the edge is the opening imbalance, and
             late breakouts are more likely noise.                                (3 variants)
  relvol     Skip days whose best candidate has relative volume below 3 / 5 / 8 / 12: average
             R rose steadily with relative volume in every test so far.           (4 variants)
  breakeven  Move the stop to the entry price once the trade is up 0.5 / 1 / 2 R: protect
             open profit.                                                          (3 variants)
  trail      Trail the stop 0.5 / 1 / 2 R behind the best price since entry: keep part of the
             big moves instead of giving them back.                                (3 variants)

Pass rule (fixed in advance): a variant passes only if its Sharpe beats the baseline in BOTH
2021-2023 and 2024-2026, each run with fresh capital. A family with several settings passes only
if at least two settings pass, including the middle one (both middle ones for an even count),
so a lone lucky value doesn't count.
Winners still need confirmation on data none of this has touched (2016-2021, or paper trading).
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import time
from time import perf_counter

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.config import data_dir
from horizon_trader.data import massive
from horizon_trader.intraday import features as F
from horizon_trader.intraday import orb
from horizon_trader.intraday.slippage import TICK, fetch_seconds, limit_fill_second

RULES = replace(orb.RULES, stop_atr=1.0)
STOP_SLIP = 0.04  # $/share, measured mean for stop-market stop-outs (574 fills, next-second open)
PERIODS = {"2021-23": (None, "2023-12-31"), "2024-26": ("2024-01-01", None)}


@dataclass(frozen=True)
class Idea:
    name: str
    family: str
    min_relvol: float = 1.0
    with_market: bool = False
    cutoff: time | None = None
    exit: str = "hold"  # hold | breakeven | trail
    exit_r: float = 0.0  # breakeven trigger or trail distance, in R
    min_gap: float = 0.0  # |open / prev close - 1| at least this (overnight-gap catalyst proxy)
    gap_agrees: bool = False  # the gap points the same way as the first 5-minute candle
    vol_regime: int = 0  # +1 = only days of above-median market volatility, -1 = below


IDEAS = [
    Idea("baseline", "baseline"),
    Idea("with SPY direction", "market", with_market=True),
    *[
        Idea(f"entries by {t:%H:%M}", "cutoff", cutoff=t)
        for t in (time(10), time(10, 30), time(11))
    ],
    *[Idea(f"relvol >= {v:g}", "relvol", min_relvol=v) for v in (3, 5, 8, 12)],
    *[Idea(f"breakeven at +{r:g}R", "breakeven", exit="breakeven", exit_r=r) for r in (0.5, 1, 2)],
    *[Idea(f"trail {r:g}R", "trail", exit="trail", exit_r=r) for r in (0.5, 1, 2)],
]

# Round 2 (pre-registered 2026-09-25, before any of it was run; `--round 2`). Same baseline and
# pass rule as round 1. 5 variants plus one control:
#   gap         the stock gapped at least 2% / 4% / 8% overnight: a free proxy for a news or
#               earnings catalyst (earnings dates need a paid data add-on)       (3 variants)
#   gap agrees  any gap, pointing the same way as the first candle: the move continues the
#               overnight news instead of fading it                               (1 variant)
#   high vol    only days when SPY's 20-day volatility is above its 1-year median: breakouts
#               are reported to pay more in volatile markets (Lundstrom 2017)     (1 variant)
#   low vol     the mirror image, as a control; not eligible to pass              (control)
IDEAS_R2 = [
    Idea("baseline", "baseline"),
    *[Idea(f"gap >= {g:.0%}", "gap", min_gap=g) for g in (0.02, 0.04, 0.08)],
    Idea("gap agrees with candle", "gap agrees", gap_agrees=True),
    Idea("high-vol days only", "high vol", vol_regime=1),
    Idea("low-vol days only (control)", "low vol (control)", vol_regime=-1),
]


# ---------------------------------------------------------------- simulation


def manage_exit(
    o,
    h,
    low,
    j: int,
    fill: float,
    side: int,
    dist: float,
    close_px: float,
    rule: str = "hold",
    r: float = 0.0,
    check_fill_minute: bool = True,
) -> tuple[float, bool, int]:
    """(exit price, stopped, exit index) of a position filled in minute j; index len(o) = close.

    Each minute the current stop is checked first (a gap through it fills at the open), then
    the rule: "target" exits at a limit `r` R away once price trades a tick through it (a gap
    through it fills at the better open); "breakeven"/"trail" move the stop for the NEXT minute
    from that minute's extreme: to the entry price once up `r` R, or `r` R behind the best
    price. Checking the stop before the target is pessimistic when a minute spans both. The fill
    minute never moves the stop. Its stop check counts any touch (pessimistic: the minute's
    range includes prices from before the fill) unless check_fill_minute=False, for callers
    that already checked the seconds after the fill (they check the target there too).
    A target exit returns stopped=False with an index before the close.
    """
    stop, best = fill - side * dist, fill
    target = fill + side * r * dist
    for i in range(j, len(o)):
        if i == j and not check_fill_minute:
            continue
        adverse = low[i] if side > 0 else h[i]
        if (adverse <= stop) if side > 0 else (adverse >= stop):
            if i == j:
                return stop, True, i
            return (min(o[i], stop) if side > 0 else max(o[i], stop)), True, i
        if rule == "target" and i > j:
            reached = h[i] >= target + TICK if side > 0 else low[i] <= target - TICK
            if reached:
                return (max(o[i], target) if side > 0 else min(o[i], target)), False, i
        if i == j or rule in ("hold", "target"):
            continue
        best = max(best, h[i]) if side > 0 else min(best, low[i])
        if rule == "breakeven" and side * (best - fill) >= r * dist:
            stop = max(stop, fill) if side > 0 else min(stop, fill)
        elif rule == "trail":
            trail = best - side * r * dist
            stop = max(stop, trail) if side > 0 else min(stop, trail)
    return close_px, False, len(o)


def market_direction() -> pd.Series:
    """Sign of SPY's first 5-minute candle per date (+1 up, -1 down, 0 flat)."""
    ors = orb._derived(f"or{RULES.minutes}")
    spy = ors[ors["ticker"] == "SPY"].set_index("date")
    return np.sign(spy["or_close"] - spy["or_open"]).astype(int)


def select(
    trades: pd.DataFrame, idea: Idea, market: pd.Series, regime: pd.Series | None = None
) -> pd.DataFrame:
    """Each day's first-ranked candidate that passes the idea's filters (traded or not).

    Candidate filters (relative volume, market direction, gap) pick the best-ranked stock that
    passes; the volatility regime is a day filter (no trade on the other days). Every input is
    known at 9:35: the gap uses today's open and yesterday's close.
    """
    c = trades[trades["relvol"] >= idea.min_relvol]
    if idea.with_market:
        m = market.reindex(c["date"]).to_numpy()
        c = c[(m == 0) | (c["side"].to_numpy() == m)]
    if idea.min_gap > 0 or idea.gap_agrees:
        gap = c["open"] / c["prev_close"] - 1
        keep = gap.abs() >= idea.min_gap
        if idea.gap_agrees:
            keep &= np.sign(gap) == c["side"]
        c = c[keep.to_numpy()]
    if idea.vol_regime:
        r = regime.reindex(c["date"]).to_numpy()
        c = c[r == idea.vol_regime]
    return c.sort_values(["date", "rank"]).groupby("date", as_index=False).head(1)


def market_volatility_regime() -> pd.Series:
    """SPY's volatility regime from the long daily history the daily sleeves use (since 1993),
    so the 1-year median is available from the first intraday day (Oct 2021)."""
    close = pd.read_parquet(data_dir() / "bars" / "SPY.parquet")["close"]
    return F.volatility_regime(close)


class Bars:
    """(day, ticker) -> (ts, open, high, low) arrays of the bars after the opening range.

    Filled once from orb.CandidateBars (one cached file) for just the keys a run needs, so it
    is small enough to hand to every worker process.
    """

    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}

    @classmethod
    def load(cls, trades: pd.DataFrame, keys) -> Bars:
        cand = orb.CandidateBars(trades, RULES.minutes)
        data = {}
        for day, ticker in keys:
            b = cand.after_or(day, ticker)
            data[(pd.Timestamp(day), ticker)] = (
                b["ts"].to_numpy(),
                *(b[f].to_numpy(float) for f in ("open", "high", "low")),
            )
        return cls(data)

    def get(self, day: pd.Timestamp, ticker: str):
        return self._data[(pd.Timestamp(day), ticker)]


def simulate(picked: pd.DataFrame, idea: Idea, bars: Bars) -> pd.DataFrame:
    """Stop-limit entry at the trigger (from 1-second bars, else a later pullback on minute
    bars), the idea's entry cutoff, then the idea's exit rule."""
    rows = []
    for _, r in picked[picked["triggered"].astype(bool)].iterrows():
        ts, o, h, lo = bars.get(r.date, r.ticker)
        side, k, limit = int(r.side), int(r.entry_idx), r.level
        secs = fetch_seconds(r.ticker, r.entry_time)
        sec = limit_fill_second(secs, side, r.level, limit)
        fill, j = (limit, k) if sec is not None else (None, k)
        stopped_in_fill_minute = None
        if sec is not None:  # check the stop on the seconds after the fill, not the whole minute
            after = secs.iloc[sec + 1 :]
            stop = limit - side * r.stop_dist
            hit = after["low"] <= stop if side > 0 else after["high"] >= stop
            if hit.any():
                first = after["open"].iloc[int(np.argmax(hit.to_numpy()))]
                stopped_in_fill_minute = min(first, stop) if side > 0 else max(first, stop)
        if fill is None:
            back = lo[k + 1 :] <= limit - TICK if side > 0 else h[k + 1 :] >= limit + TICK
            if not back.any():
                continue
            fill, j = limit, k + 1 + int(np.argmax(back))
        t = pd.Timestamp(ts[j])
        entry_time = t if t.tzinfo else t.tz_localize("UTC").tz_convert(massive.TZ)
        if idea.cutoff is not None and entry_time.time() > idea.cutoff:
            continue
        if stopped_in_fill_minute is not None:
            px, stopped, x = stopped_in_fill_minute, True, j
        else:
            px, stopped, x = manage_exit(
                o,
                h,
                lo,
                j,
                fill,
                side,
                r.stop_dist,
                r.close,
                idea.exit,
                idea.exit_r,
                check_fill_minute=sec is None,
            )
        rows.append(
            r.to_dict()
            | {
                "rank": 1,
                "triggered": True,
                "entry_px": fill,
                "entry_idx": j,
                "entry_time": entry_time,
                "exit_px_path": px,
                "stopped_path": stopped,
                "exit_idx_path": x,
                "entry_slip": 0.0,
                "exit_slip": STOP_SLIP,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- evaluation


def evaluate(sim: pd.DataFrame, calendar: pd.DatetimeIndex, equity: float = 5_000.0) -> dict:
    """Stats for the whole period and each half, every run starting with fresh capital."""
    acct = orb.Account(equity=equity, top_n=1, plan="tiered", slippage=None)
    out = {}
    for label, (a, b) in {"all": (None, None), **PERIODS}.items():
        cal = calendar[
            (calendar >= pd.Timestamp(a or "1900")) & (calendar <= pd.Timestamp(b or "2100"))
        ]
        t = sim[sim["date"].isin(cal)] if len(sim) else sim
        eq, fills = (
            orb.run_portfolio(t, acct, cal)
            if len(t)
            else (pd.Series(equity, index=cal), pd.DataFrame())
        )
        s = A.equity_stats(eq)
        out[f"Sharpe {label}"] = s["Sharpe"]
        if label == "all":
            pnl = fills["pnl"] if len(fills) else pd.Series(dtype=float)
            wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
            out |= {
                "CAGR": s["CAGR"],
                "max DD": s["max DD"],
                "trades/yr": len(fills) / s["years"],
                "win rate": (pnl > 0).mean(),
                "profit factor": wins / losses if losses else np.nan,
                "avg R": orb.r_multiple(t, "path").mean() if len(t) else np.nan,
            }
    return out


def verdicts(table: pd.DataFrame) -> pd.DataFrame:
    base = table.loc["baseline"]
    t = table.copy()
    t["beats base 21-23"] = t["Sharpe 2021-23"] > base["Sharpe 2021-23"]
    t["beats base 24-26"] = t["Sharpe 2024-26"] > base["Sharpe 2024-26"]
    t["passes"] = t["beats base 21-23"] & t["beats base 24-26"]
    flags = ["beats base 21-23", "beats base 24-26", "passes"]
    t[flags] = t[flags].astype(object)  # the baseline row gets "-" instead of True/False
    t.loc["baseline", flags] = "-"
    return t


def family_verdict(table: pd.DataFrame) -> dict[str, str]:
    out = {}
    for fam, g in table.groupby("family", sort=False):
        if fam == "baseline":
            continue
        passed = g["passes"] == True  # noqa: E712  (object column: True / False)
        if len(g) == 1:
            ok = passed.all()
        else:
            middle = (
                g.index[len(g) // 2] if len(g) % 2 else g.index[len(g) // 2 - 1 : len(g) // 2 + 1]
            )
            ok = passed.sum() >= 2 and passed.loc[middle].all()
        out[fam] = "PASS" if ok else "fail"
    return out


_BARS: Bars | None = None


def _init_worker(bars: Bars) -> None:
    global _BARS
    _BARS = bars


def run_idea(job: tuple[Idea, pd.DataFrame, pd.DatetimeIndex]):
    """Simulate and evaluate one variant (runs in a worker process)."""
    idea, picked, calendar = job
    sim = simulate(picked, idea, _BARS)
    row = {"family": idea.family} | evaluate(sim, calendar)
    row["Sharpe all $20k"] = evaluate(sim, calendar, 20_000.0)["Sharpe all"]
    return idea.name, row, sim


def run_ideas(trades: pd.DataFrame, ideas: list[Idea], n_workers: int | None = None):
    """All variants in parallel: selections are made up front, the bars they need are loaded
    once from the candidate-bar cache and shipped to each worker."""
    calendar = pd.DatetimeIndex(sorted(trades["date"].unique()))
    market = market_direction()
    regime = market_volatility_regime() if any(i.vol_regime for i in ideas) else None
    picks = {idea.name: select(trades, idea, market, regime) for idea in ideas}
    keys = {
        (r.date, r.ticker)
        for p in picks.values()
        for r in p[p["triggered"].astype(bool)].itertuples()
    }
    bars = Bars.load(trades, sorted(keys))
    jobs = [(idea, picks[idea.name], calendar) for idea in ideas]
    n = min(len(jobs), orb.workers(n_workers))
    if n == 1:
        _init_worker(bars)
        results = [run_idea(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=n, initializer=_init_worker, initargs=(bars,)) as pool:
            results = list(pool.map(run_idea, jobs))
    rows = {name: row for name, row, _ in results}
    sims = {name: sim for name, _, sim in results}
    return rows, sims, calendar


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--save", action="store_true", help="save the baseline and passing variants")
    p.add_argument(
        "--workers", type=int, default=None, help="worker processes (default: cores - 2)"
    )
    p.add_argument("--round", type=int, choices=(1, 2), default=1, help="idea batch to run")
    args = p.parse_args()

    t0 = perf_counter()
    trades = orb.build_trades(RULES)
    ideas = IDEAS if args.round == 1 else IDEAS_R2
    rows, sims, calendar = run_ideas(trades, ideas, args.workers)
    print(f"  {len(ideas)} variants in {perf_counter() - t0:.0f}s", flush=True)
    table = verdicts(pd.DataFrame(rows).T)
    fams = family_verdict(table)

    pct = ("CAGR", "max DD", "win rate")
    show = table.copy()
    for c in show.columns:
        if c in pct:
            show[c] = show[c].map(lambda v: f"{v:.1%}")
        elif c not in ("family", "beats base 21-23", "beats base 24-26", "passes"):
            show[c] = show[c].map(lambda v: f"{v:.2f}" if pd.notna(v) else "-")
    first, last = calendar[0].date(), calendar[-1].date()
    print(f"\nORB ideas, {first} .. {last}: top-1, 1 ATR stop, stop-limit entry, $5k IBKR Tiered")
    print(f"round {args.round}: {len(ideas) - 1} variants tested against the baseline\n")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(show.to_string())
    print("\nfamily verdicts (>= 2 settings pass incl. the middle one):", fams)

    if args.save:
        keep = ["baseline"] + [n for n in table.index if table.loc[n, "passes"] is True]
        for name in keep:
            acct = orb.Account(equity=5_000.0, top_n=1, plan="tiered", slippage=None)
            extra = {
                "caveats": [
                    *orb.ORB_CAVEATS,
                    f"One of {len(ideas) - 1} pre-registered variants "
                    "tested on the same data (orb_ideas.py).",
                ]
            }
            print(
                "saved",
                orb.save_orb_run(f"ORB idea: {name}", sims[name], acct, RULES, extra, calendar),
            )


if __name__ == "__main__":
    main()
