"""Inverted ORB: fade the opening-range breakout instead of following it.

    uv run python -m horizon_trader.intraday.orb_inverted

The owner's question: ORB gets stopped out on most days, so would doing the opposite win more
often with smaller gains? Pre-registered 2026-09-27, before running. Same candidates as ORB
(top N by relative volume, 5-minute opening range, 1 ATR = the robustness setup's stop), same
sizing (1% of equity at a 1 ATR stop, at most 4x), $5k IBKR Pro Tiered:

  ORB  the baseline: follow the breakout (stop order at the range high after an up candle,
       low after a down one), stop 1 ATR, exit at the close.
  M    mirror: take the other side of every ORB trade. Sell (limit) at the breakout level,
       take profit where ORB's stop was (1 ATR), no stop, exit at the close. Before costs it
       is exactly minus ORB, trade for trade.
  F    fade with a stop: sell at the breakout level, stop 1 ATR above, exit at the close.
  B    fade bracket: sell at the breakout level, stop 1 ATR, profit target 1 ATR.
  X    flipped direction ("short when the first candle closes up"): stop order at the range
       LOW after an up candle (short), HIGH after a down one (long), stop 1 ATR, close exit.
       ORB's mechanics with the direction rule reversed.

Fills: minute bars walked open -> low -> high -> close for up bars, open -> high -> low ->
close for down bars (ORB's "path" convention; this module reproduces ORB's own path results
exactly, which is checked at run time). Limit orders (fade entries, targets) fill when the
price touches them, at the limit or better on a gap: optimistic, since a real limit order at
the level may not fill when the price only touches it and reverses, which are exactly the
fade's best trades. Stop orders (ORB/X entries, all stops) pay slippage in the "4c" rows:
the measured mean for stop-market fills on 1-second bars. Market-on-close exits pay none.
Pass rule: a variant passes only if its Sharpe beats ORB's in BOTH 2021-23 and 2024-26.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np
import pandas as pd

from horizon_trader.intraday import features as F
from horizon_trader.intraday import orb

STOP_ATR = 1.0
TOP = 20  # candidates simulated per day; portfolios take the top N of these
STOP_SLIP = 0.04  # $/share on stop-order fills (measured mean, 1-second bars)
PERIODS = {"all": (None, None), "2021-23": (None, "2023-12-31"), "2024-26": ("2024-01-01", None)}


@dataclass(frozen=True)
class Variant:
    name: str
    label: str
    fade: bool  # position against the first candle's direction
    trigger_same: bool  # entry at ORB's breakout level (True) or at the opposite side (False)
    stop: float | None  # in ATR
    target: float | None  # in ATR
    limit_entry: bool


VARIANTS = [
    Variant("ORB", "follow the breakout (baseline)", False, True, STOP_ATR, None, False),
    Variant("M", "mirror: fade, target 1 ATR, no stop", True, True, None, STOP_ATR, True),
    Variant("F", "fade, stop 1 ATR, exit at close", True, True, STOP_ATR, None, True),
    Variant("B", "fade bracket: stop 1 ATR, target 1 ATR", True, True, STOP_ATR, STOP_ATR, True),
    Variant(
        "X",
        "flipped: short a break of the low after an up candle",
        True,
        False,
        STOP_ATR,
        None,
        False,
    ),
]


# Added 2026-09-27 AFTER seeing the results above (the owner asked about 2:1 brackets), so
# exploratory: 9 fade brackets, stop x target in ATR. Break-even win rate = stop / (stop +
# target) if every trade ends at one of the two (close exits make it approximate).
BRACKETS = [
    Variant(f"B{s:g}/{t:g}", f"fade, stop {s:g} ATR, target {t:g} ATR", True, True, s, t, True)
    for s in (0.5, 1.0, 2.0)
    for t in (0.5, 1.0, 2.0)
]


# ---------------------------------------------------------------- the bar walker


def _path(o: float, h: float, low: float, c: float) -> tuple[float, float, float, float]:
    """Price path inside one minute bar (ORB's "path" convention)."""
    return (o, low, h, c) if c >= o else (o, h, low, c)


def _exit_on_path(pts, side: int, stop: float | None, target: float | None, at_open: bool):
    """First stop/target hit along a price path that starts inside the bracket (or, with
    `at_open`, may gap beyond it: then the fill is the open). Returns (reason, price) or None."""
    if at_open:
        p = pts[0]
        if stop is not None and (p <= stop if side > 0 else p >= stop):
            return "stop", p
        if target is not None and (p >= target if side > 0 else p <= target):
            return "target", p
    for b in pts[1:]:  # each segment is monotone, so only one level can be crossed in it
        if stop is not None and (b <= stop if side > 0 else b >= stop):
            return "stop", stop
        if target is not None and (b >= target if side > 0 else b <= target):
            return "target", target
    return None


def simulate(
    o,
    h,
    low,
    c,
    side: int,
    level: float,
    trigger_up: bool,
    stop_dist: float | None,
    target_dist: float | None,
    close_px: float,
) -> dict | None:
    """One trade on the bars after the opening range. `side` is the position (+1 long, -1
    short); the entry fills when the price reaches `level` moving up (`trigger_up`) or down,
    at the level or at the open if the bar gapped through it. Exit at the stop, the target,
    or `close_px`. None if the entry never triggers."""
    hits = np.flatnonzero(h >= level) if trigger_up else np.flatnonzero(low <= level)
    if not len(hits):
        return None
    k = int(hits[0])
    gapped = o[k] >= level if trigger_up else o[k] <= level
    fill = o[k] if gapped else level
    stop = fill - side * stop_dist if stop_dist is not None else None
    target = fill + side * target_dist if target_dist is not None else None
    pts = _path(o[k], h[k], low[k], c[k])
    if not gapped:  # the part of the entry bar after the level was crossed
        for i in range(3):
            a, b = pts[i], pts[i + 1]
            if (a < level <= b) if trigger_up else (a > level >= b):
                pts = (level, *pts[i + 1 :])
                break
    out = {"entry_idx": k, "entry_px": fill}
    hit = _exit_on_path(pts, side, stop, target, at_open=False)
    j = k
    if hit is None:
        later = np.zeros(len(o) - k - 1, bool)
        if stop is not None:
            later |= (low[k + 1 :] <= stop) if side > 0 else (h[k + 1 :] >= stop)
        if target is not None:
            later |= (h[k + 1 :] >= target) if side > 0 else (low[k + 1 :] <= target)
        idx = np.flatnonzero(later)
        if len(idx):
            j = k + 1 + int(idx[0])
            hit = _exit_on_path(_path(o[j], h[j], low[j], c[j]), side, stop, target, True)
    if hit is None:
        return out | {"exit_idx": len(o), "exit_px": close_px, "reason": "close"}
    return out | {"exit_idx": j, "exit_px": hit[1], "reason": hit[0]}


# ---------------------------------------------------------------- all candidates, all variants


def _arrays(cb: orb.CandidateBars, day: pd.Timestamp, ticker: str, minutes: int):
    a, b = cb._slices.get((pd.Timestamp(day).value, ticker), (0, 0))
    if a == b:
        return None
    ts = cb._ts.iloc[a:b]
    cut = F.session_open(pd.Timestamp(day).date()) + pd.Timedelta(minutes=minutes)
    after = (ts >= cut).to_numpy()
    cols = {k: cb._cols[k][a:b] for k in ("open", "high", "low", "close")}
    or_high, or_low = cols["high"][~after].max(), cols["low"][~after].min()
    return {k: v[after] for k, v in cols.items()}, or_high, or_low


def build(
    cands: pd.DataFrame, cb: orb.CandidateBars, minutes: int = 5, variants=None
) -> pd.DataFrame:
    """Every candidate x variant, in orb.run_portfolio's trade format (exit_px_path etc.).
    Positions are sized on the variant's own stop distance (1 ATR when it has no stop), so
    every trade risks 1% of equity at its stop and R is in units of that stop."""
    rows = []
    for r in cands.itertuples():
        got = _arrays(cb, r.date, r.ticker, minutes)
        if got is None:
            continue
        bars, or_high, or_low = got
        o, h, lo, c = bars["open"], bars["high"], bars["low"], bars["close"]
        for v in variants or VARIANTS:
            side = -r.side if v.fade else r.side
            if v.trigger_same:  # ORB's level: the range high after an up candle
                level, trigger_up = (or_high, True) if r.side > 0 else (or_low, False)
            else:  # the opposite side of the range, in the new direction
                level, trigger_up = (or_high, True) if side > 0 else (or_low, False)
            res = simulate(
                o,
                h,
                lo,
                c,
                side,
                level,
                trigger_up,
                v.stop and v.stop * r.atr,
                v.target and v.target * r.atr,
                r.close,
            )
            row = {
                "variant": v.name,
                "date": r.date,
                "ticker": r.ticker,
                "rank": r.rank,
                "relvol": r.relvol,
                "side": side,
                "stop_dist": (v.stop or STOP_ATR) * r.atr,
                "triggered": res is not None,
                "limit_entry": v.limit_entry,
            }
            if res is not None:
                row |= {
                    "entry_idx": res["entry_idx"],
                    "entry_px": res["entry_px"],
                    "exit_idx_path": res["exit_idx"],
                    "exit_px_path": res["exit_px"],
                    "reason": res["reason"],
                    "stopped_path": res["reason"] == "stop",
                }
            rows.append(row)
    return pd.DataFrame(rows)


def with_slippage(t: pd.DataFrame, slip: float) -> pd.DataFrame:
    """Per-trade slippage for run_portfolio: stop-order entries pay `slip`, limit entries
    none; exits pay it only at a stop (run_portfolio multiplies exit_slip by stopped)."""
    return t.assign(entry_slip=np.where(t["limit_entry"], 0.0, slip), exit_slip=slip)


def r_multiples(t: pd.DataFrame) -> pd.Series:
    return t["side"] * (t["exit_px_path"] - t["entry_px"]) / t["stop_dist"]


def quality(t: pd.DataFrame) -> dict:
    """Before-cost trade shape: how often it wins, by how much, and where the R comes from."""
    r = r_multiples(t)
    wins, losses = r[r > 0], r[r <= 0]
    return {
        "trades": len(r),
        "win rate": (r > 0).mean(),
        "avg win R": wins.mean(),
        "avg loss R": losses.mean(),
        "avg R": r.mean(),
        "median R": r.median(),
        "worst R": r.min(),
        "best R": r.max(),
        "total R": r.sum(),
    }


def money(t: pd.DataFrame, top_n: int, slip: float, calendar: pd.DatetimeIndex) -> dict:
    out = {}
    for period, (a, b) in PERIODS.items():
        d = t
        cal = calendar
        if a:
            d, cal = d[d["date"] >= a], cal[cal >= a]
        if b:
            d, cal = d[d["date"] <= b], cal[cal <= b]
        acct = orb.Account(equity=5_000.0, top_n=top_n, plan="tiered", slippage=None)
        eq, fills = orb.run_portfolio(with_slippage(d, slip), acct, cal)
        s = orb._stats(eq, fills)
        out[period] = {
            "CAGR": s.get("CAGR"),
            "Sharpe": s.get("Sharpe"),
            "max DD": s.get("max DD"),
            "hit": s.get("hit"),
            "$/trade": s.get("$/trade"),
        }
    return out


def bracket_report(cands, cb, calendar, minutes: int = 5) -> None:
    t = build(cands, cb, minutes, BRACKETS)
    rows = []
    for v in BRACKETS:
        d = t[t["variant"] == v.name]
        q = quality(d[d["triggered"] & (d["rank"] <= 1)])
        row = {
            "risk:reward": f"{v.stop:g} : {v.target:g}",
            "win rate": q["win rate"],
            "break-even win rate": v.stop / (v.stop + v.target),
            "avg R": q["avg R"],
            "worst R": q["worst R"],
        }
        for slip in (0.0, STOP_SLIP):
            res = money(d, 1, slip, calendar)
            tag = f"{slip * 100:.0f}c"
            row |= {
                f"CAGR {tag}": res["all"]["CAGR"],
                f"Sharpe {tag}": res["all"]["Sharpe"],
                f"Sharpe 21-23 / 24-26 {tag}": f"{res['2021-23']['Sharpe']:+.2f} / "
                f"{res['2024-26']['Sharpe']:+.2f}",
            }
        rows.append(row)
    df = pd.DataFrame(rows, index=[v.label for v in BRACKETS])
    for col in ("win rate", "break-even win rate", "CAGR 0c", "CAGR 4c"):
        df[col] = df[col].map(lambda x: f"{x:.1%}")
    print("=== EXPLORATORY fade brackets, $5k top 1, IBKR Tiered (added after the main test) ===")
    print(df.to_string(float_format=lambda x: f"{x:+.2f}"))


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--brackets", action="store_true", help="exploratory fade bracket grid only")
    args = p.parse_args()
    pd.set_option("display.width", 250)
    t0 = perf_counter()
    rules = orb.OrbRules(stop_atr=STOP_ATR)
    table = orb.build_trades(rules)
    calendar = pd.DatetimeIndex(sorted(table["date"].unique()))
    cands = table[table["rank"] <= TOP]
    cb = orb.CandidateBars(cands, rules.minutes)
    if args.brackets:
        bracket_report(cands, cb, calendar, rules.minutes)
        return
    all_t = build(cands, cb, rules.minutes)
    print(
        f"simulated {len(cands):,} candidates x {len(VARIANTS)} variants "
        f"in {perf_counter() - t0:.0f}s\n"
    )

    # checks: this walker reproduces ORB's own simulation, and M is exactly minus ORB
    mine = all_t[all_t["variant"] == "ORB"].set_index(["date", "ticker"])
    ref = cands.set_index(["date", "ticker"])
    both = mine.join(ref[["exit_px_path", "triggered"]], rsuffix="_orb")
    trig = both["triggered"] & both["triggered_orb"]
    same = np.isclose(both.loc[trig, "exit_px_path"], both.loc[trig, "exit_px_path_orb"])
    print(
        f"check vs orb.py (path): triggers agree "
        f"{(both['triggered'] == both['triggered_orb']).mean():.2%}, "
        f"exit prices agree {same.mean():.2%} of {trig.sum():,} trades"
    )
    m = all_t[all_t["variant"] == "M"].set_index(["date", "ticker"])
    gap = (r_multiples(m) + r_multiples(mine)).abs().max()
    print(f"check: mirror R + ORB R = 0 on every trade (max abs {gap:.1e})\n")

    trig_t = all_t[all_t["triggered"]]
    for top_n in (1, 20):
        print(f"=== trade shape before costs, top {top_n} ===")
        q = {
            v.name: quality(trig_t[(trig_t["variant"] == v.name) & (trig_t["rank"] <= top_n)])
            for v in VARIANTS
        }
        qt = pd.DataFrame(q).T
        qt.index = [f"{v.name}. {v.label}" for v in VARIANTS]
        qt["trades"] = qt["trades"].map(lambda x: f"{x:,.0f}")
        qt["win rate"] = qt["win rate"].map(lambda x: f"{x:.0%}")
        print(qt.to_string(float_format=lambda x: f"{x:+.2f}"), "\n")

    for slip in (0.0, STOP_SLIP):
        print(f"=== $5k top 1, IBKR Tiered, {slip * 100:.0f}c slippage on stop-order fills ===")
        rows, sharpe = [], {}
        for v in VARIANTS:
            res = money(all_t[all_t["variant"] == v.name], 1, slip, calendar)
            sharpe[v.name] = {p: res[p]["Sharpe"] for p in PERIODS}
            for p, s in res.items():
                rows.append({"variant": f"{v.name}. {v.label}", "period": p} | s)
        df = pd.DataFrame(rows).set_index(["variant", "period"])
        fmt = df.copy().astype(object)
        for col in ("CAGR", "max DD", "hit"):
            fmt[col] = df[col].map(lambda x: f"{x:+.1%}")
        for col in ("Sharpe", "$/trade"):
            fmt[col] = df[col].map(lambda x: f"{x:+.2f}")
        print(fmt.to_string())
        verdict = {
            v.name: all(sharpe[v.name][p] > sharpe["ORB"][p] for p in ("2021-23", "2024-26"))
            for v in VARIANTS[1:]
        }
        print(
            "pass (beats ORB's Sharpe in both halves): "
            + ", ".join(f"{k} {'PASS' if ok else 'fail'}" for k, ok in verdict.items()),
            "\n",
        )


if __name__ == "__main__":
    main()
