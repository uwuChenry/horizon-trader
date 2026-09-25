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
from dataclasses import dataclass, replace
from datetime import time

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.data import massive
from horizon_trader.intraday import features as F
from horizon_trader.intraday import orb
from horizon_trader.intraday.slippage import TICK, fetch_seconds, limit_fill_in_seconds

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
) -> tuple[float, bool, int]:
    """(exit price, stopped, exit index) of a position filled in minute j; index len(o) = close.

    Each minute the current stop is checked first (a gap through it fills at the open; a touch
    in the fill minute counts), then the stop is moved for the NEXT minute from that minute's
    extreme: to the entry price once up `r` R (breakeven), or `r` R behind the best price
    (trail). The fill minute itself never moves the stop (its pre-fill range is unknowable).
    """
    stop, best = fill - side * dist, fill
    for i in range(j, len(o)):
        adverse = low[i] if side > 0 else h[i]
        if (adverse <= stop) if side > 0 else (adverse >= stop):
            if i == j:
                return stop, True, i
            return (min(o[i], stop) if side > 0 else max(o[i], stop)), True, i
        if i == j or rule == "hold":
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


def select(trades: pd.DataFrame, idea: Idea, market: pd.Series) -> pd.DataFrame:
    """Each day's first-ranked candidate that passes the idea's filters (traded or not)."""
    c = trades[trades["relvol"] >= idea.min_relvol]
    if idea.with_market:
        m = market.reindex(c["date"]).to_numpy()
        c = c[(m == 0) | (c["side"].to_numpy() == m)]
    return c.sort_values(["date", "rank"]).groupby("date", as_index=False).head(1)


class Bars:
    """Session minute bars after the opening range, per (day, ticker), cached in memory."""

    def __init__(self) -> None:
        self._cache: dict = {}

    def get(self, day: pd.Timestamp, ticker: str):
        key = (day, ticker)
        if key not in self._cache:
            start = F.session_open(day.date())
            window = [
                ("ticker", "==", ticker),
                ("ts", ">=", start + pd.Timedelta(minutes=RULES.minutes)),
                ("ts", "<", start + orb.CLOSE_TIME),
            ]
            b = pd.read_parquet(massive.local_path("minute", day.date()), filters=window)
            b = b.sort_values("ts")
            self._cache[key] = (
                b["ts"].to_numpy(),
                *(b[f].to_numpy(float) for f in ("open", "high", "low")),
            )
        return self._cache[key]


def simulate(picked: pd.DataFrame, idea: Idea, bars: Bars) -> pd.DataFrame:
    """Stop-limit entry at the trigger (from 1-second bars, else a later pullback on minute
    bars), the idea's entry cutoff, then the idea's exit rule."""
    rows = []
    for _, r in picked[picked["triggered"].astype(bool)].iterrows():
        ts, o, h, lo = bars.get(r.date, r.ticker)
        side, k, limit = int(r.side), int(r.entry_idx), r.level
        fill, j = (
            limit_fill_in_seconds(fetch_seconds(r.ticker, r.entry_time), side, r.level, limit),
            k,
        )
        if fill is None:
            back = lo[k + 1 :] <= limit - TICK if side > 0 else h[k + 1 :] >= limit + TICK
            if not back.any():
                continue
            fill, j = limit, k + 1 + int(np.argmax(back))
        t = pd.Timestamp(ts[j])
        entry_time = t if t.tzinfo else t.tz_localize("UTC").tz_convert(massive.TZ)
        if idea.cutoff is not None and entry_time.time() > idea.cutoff:
            continue
        px, stopped, x = manage_exit(
            o, h, lo, j, fill, side, r.stop_dist, r.close, idea.exit, idea.exit_r
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


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--save", action="store_true", help="save the baseline and passing variants")
    args = p.parse_args()

    trades = orb.build_trades(RULES)
    calendar = pd.DatetimeIndex(sorted(trades["date"].unique()))
    market, bars = market_direction(), Bars()
    rows, sims = {}, {}
    for idea in IDEAS:
        sims[idea.name] = sim = simulate(select(trades, idea, market), idea, bars)
        rows[idea.name] = {"family": idea.family} | evaluate(sim, calendar)
        rows[idea.name]["Sharpe all $20k"] = evaluate(sim, calendar, 20_000.0)["Sharpe all"]
        print(f"  {idea.name:<22} done", flush=True)
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
    print(f"{len(IDEAS) - 1} variants tested against the baseline\n")
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
                    f"One of {len(IDEAS) - 1} pre-registered variants "
                    "tested on the same data (orb_ideas.py).",
                ]
            }
            print(
                "saved",
                orb.save_orb_run(f"ORB idea: {name}", sims[name], acct, RULES, extra, calendar),
            )


if __name__ == "__main__":
    main()
