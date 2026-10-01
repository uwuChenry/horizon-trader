"""Dual-class share arbitrage: #1 on paperswithbacktest.com ("Self-Imposed Limits to Arbitrage").

    uv run python -m horizon_trader.pwb.dual_class

The paper (Maymin 2011, J. Applied Finance; https://ssrn.com/abstract=1088553) explains why
mispricings between identical share classes (HSBC, Royal Dutch/Shell, 3Com/Palm) persist. It
has no trading rule. The site's code trades 7 US dual-class pairs (BF, CRD, GTN, HVT, MOG, TAP,
WSO: read from its current positions) and reports Sharpe 1.97 (2.37 from its monthly NAV),
7.7%/yr at 3.2% vol, 1990-2026. Four of those B legs have zero volume on 41-58% of days.

Rule, fixed before running (textbook pairs trading, Gatev, Goetzmann & Rouwenhorst 2006,
https://doi.org/10.1093/rfs/hhj020):
  spread  s = log(adj close A) - log(adj close B); z = (s - 60-day mean) / 60-day std
  open    |z| >= 2: short the rich leg, long the cheap one, 1/N of equity per leg
          (N = pairs in the universe, so gross never exceeds 2x)
  close   when z crosses zero, or the pair stops being tradeable
Execution variants (signal always from the close of day t):
  same close   fill at the close of day t, the price the signal was computed from
               (what a naive daily backtest does; on a stale or bid/ask-bounced close it
               captures reversal that can't be traded)
  next close   fill at the close of day t+1
  next open    fill at the open of day t+1 (this repo's convention)
  traded days  next close, but a leg's weight only changes on a day it actually traded
               (volume > 0); until then the old position stays on, legs can be unhedged
Costs: a half-spread per ticker from daily high/low/close (Abdi & Ranaldo 2017,
https://doi.org/10.1093/rfs/hhx084), 60-day window ending the day before, charged on every
change in weight; plus IBKR Pro Tiered commissions for a $5k or $100k account. Short borrow
fees are not modelled (thin B shares are often hard to borrow), so net results are optimistic.
Universes:
  pwb7        the site's 7 pairs, no liquidity filter (the replication)
  pwb7 liquid the same pairs, traded only while both legs had volume on each of the previous
              20 days and a 60-day median dollar volume >= $1M (point-in-time)
  all liquid  those 7 plus 18 more US dual-class pairs, same filter. BRK-A is left out
              (one share costs more than the account)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.datasources.store import load_bars
from horizon_trader.execution.costs import ibkr_costs

PWB_PAIRS = [
    ("BF-A", "BF-B"), ("CRD-A", "CRD-B"), ("GTN", "GTN-A"), ("HVT", "HVT-A"),
    ("MOG-A", "MOG-B"), ("TAP", "TAP-A"), ("WSO", "WSO-B"),
]  # fmt: skip
OTHER_PAIRS = [
    ("LEN", "LEN-B"), ("HEI", "HEI-A"), ("GOOGL", "GOOG"), ("FOXA", "FOX"), ("NWSA", "NWS"),
    ("GEF", "GEF-B"), ("MKC", "MKC-V"), ("BIO", "BIO-B"), ("UAA", "UA"), ("FWONA", "FWONK"),
    ("BATRA", "BATRK"), ("KELYA", "KELYB"), ("BELFA", "BELFB"), ("RUSHA", "RUSHB"),
    ("SENEA", "SENEB"), ("BH", "BH-A"), ("AGM", "AGM-A"), ("LILA", "LILAK"),
]  # fmt: skip
LOOKBACK, ENTRY = 60, 2.0
MIN_DOLLAR_VOLUME, QUIET_DAYS = 1e6, 20
PUBLISHED = "2007-12-31"  # SSRN working paper; journal version 2011


def zscore(spread: pd.Series, lookback: int = LOOKBACK) -> pd.Series:
    """Causal z-score: row t uses spread values up to and including t."""
    m = spread.rolling(lookback).mean()
    s = spread.rolling(lookback).std()
    return (spread - m) / s


def pair_position(z: pd.Series, tradeable: pd.Series, entry: float = ENTRY) -> pd.Series:
    """+1 = long A / short B, -1 = the reverse, 0 = flat. Opens at |z| >= entry, closes when
    z crosses zero or the pair stops being tradeable. Row t uses z and tradeable up to t."""
    out = np.zeros(len(z))
    pos = 0.0
    for i, (zi, ok) in enumerate(zip(z.to_numpy(), tradeable.to_numpy(), strict=True)):
        if not ok or np.isnan(zi):
            pos = 0.0
        elif pos == 0.0:
            if zi >= entry:
                pos = -1.0  # A is rich: short A, long B
            elif zi <= -entry:
                pos = 1.0
        elif pos * zi >= 0:  # z crossed (or touched) zero
            pos = 0.0
        out[i] = pos
    return pd.Series(out, index=z.index)


def half_spread(bars: dict[str, pd.DataFrame], window: int = LOOKBACK) -> pd.DataFrame:
    """Abdi-Ranaldo effective half-spread per ticker, from a window ending the day before."""
    c = np.log(bars["close"])
    eta = (np.log(bars["high"]) + np.log(bars["low"])) / 2
    s2 = 4 * (c - eta) * (c - eta.shift(-1))  # uses t+1, so shift the window back a day
    s2 = s2.rolling(window, min_periods=window // 2).mean().shift(2)
    return np.sqrt(s2.clip(lower=0)) / 2


def tradeable(bars: dict[str, pd.DataFrame], a: str, b: str) -> pd.Series:
    """Both legs traded on each of the last QUIET_DAYS days and had a 60-day median dollar
    volume of at least MIN_DOLLAR_VOLUME (row t uses data up to t)."""
    ok = pd.Series(True, index=bars["close"].index)
    for s in (a, b):
        vol = bars["volume"][s]
        dv = (vol * bars["close"][s]).rolling(LOOKBACK).median()
        traded = (vol > 0).astype(float).rolling(QUIET_DAYS).min() == 1
        ok &= traded & (dv >= MIN_DOLLAR_VOLUME)
    return ok


def weights(
    bars: dict[str, pd.DataFrame], pairs: list[tuple[str, str]], liquid: bool
) -> pd.DataFrame:
    """Target weights decided at each close (date x ticker)."""
    close = bars["close"]
    w = pd.DataFrame(0.0, index=close.index, columns=sorted({s for p in pairs for s in p}))
    n = len(pairs)
    for a, b in pairs:
        both = close[a].notna() & close[b].notna()
        spread = np.log(close[a]) - np.log(close[b])
        ok = both & (tradeable(bars, a, b) if liquid else True)
        pos = pair_position(zscore(spread), ok)
        w[a] += pos / n
        w[b] -= pos / n
    return w


def simulate(
    bars: dict[str, pd.DataFrame],
    w: pd.DataFrame,
    fill: str = "next close",
    spread: pd.DataFrame | None = None,
    capital: float | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Daily equity multiple and per-day cost/turnover. `fill` is 'same close', 'next close' or
    'next open'. Cash earns nothing (IBKR pays no interest on the first $10k); short
    proceeds are assumed to fund the long leg."""
    cols = list(w.columns)
    close, open_ = bars["close"][cols], bars["open"][cols]
    r_cc = close.pct_change(fill_method=None).fillna(0.0)
    r_oc = (close / open_ - 1).fillna(0.0)
    held = w if fill == "same close" else w.shift(1).fillna(0.0)  # weight in force after day t
    if fill == "traded days":  # an order waits until the stock prints a trade
        traded = bars["volume"][cols].fillna(0.0) > 0
        held = held.where(traded).ffill().fillna(0.0)
    prev = held.shift(1).fillna(0.0)
    if fill == "next open":
        # yesterday's book earns close-to-close; the change made at today's open earns open-to-close
        gross = (prev * r_cc).sum(axis=1) + ((held - prev) * r_oc).sum(axis=1)
        exec_px = open_
    else:
        gross = (prev * r_cc).sum(axis=1)
        exec_px = close
    turnover = (held - prev).abs()
    spread_cost = (turnover * spread[cols].fillna(0.0)).sum(axis=1) if spread is not None else 0.0
    eq = np.empty(len(gross))
    comm = np.zeros(len(gross))
    level = 1.0
    costs = ibkr_costs("tiered", 0.0)
    trades = turnover.to_numpy()
    px = exec_px.to_numpy()
    g = gross.to_numpy()
    sc = np.asarray(spread_cost if spread is not None else np.zeros(len(g)))
    for i in range(len(g)):
        level *= 1 + g[i] - sc[i]
        if capital is not None:
            dollars = 0.0
            for j in np.nonzero(trades[i] > 1e-12)[0]:
                value = trades[i, j] * level * capital
                dollars += costs.total(value / px[i, j], px[i, j])
            comm[i] = dollars / (level * capital)
            level *= 1 - comm[i]
        eq[i] = level
    detail = pd.DataFrame(
        {"gross": gross, "spread": sc, "commission": comm, "turnover": turnover.sum(axis=1)},
        index=gross.index,
    )
    return pd.Series(eq, index=gross.index), detail


def stats(eq: pd.Series, detail: pd.DataFrame, w: pd.DataFrame) -> dict[str, float]:
    active = eq.index[(w.abs().sum(axis=1) > 0).cummax()]
    eq = eq.loc[active[0] :] if len(active) else eq
    s = A.equity_stats(eq)
    years = s["years"]
    changes = w.diff().abs().gt(1e-12).sum(axis=1)
    return {
        "CAGR": s["CAGR"],
        "vol": s["vol"],
        "Sharpe": s["Sharpe"],
        "max DD": s["max DD"],
        "gross/yr": detail["gross"].loc[eq.index].sum() / years,
        "spread cost/yr": detail["spread"].loc[eq.index].sum() / years,
        "commission/yr": detail["commission"].loc[eq.index].sum() / years,
        "orders/yr": changes.loc[eq.index].sum() / years,
        "break-even half-spread": detail["gross"].loc[eq.index].sum()
        / max(detail["turnover"].loc[eq.index].sum(), 1e-12),
        "% time invested": (w.loc[eq.index].abs().sum(axis=1) > 0).mean(),
    }


def per_pair(bars, pairs, liquid: bool, spread: pd.DataFrame) -> pd.DataFrame:
    rows = {}
    for p in pairs:
        w = weights(bars, [p], liquid)
        eq_g, d = simulate(bars, w, "same close")
        eq_n, dn = simulate(bars, w, "next close", spread)
        eq_t, dt = simulate(bars, w, "traded days")
        vol = bars["volume"][list(p)]
        start = bars["close"][list(p)].dropna().index[0]
        rows[f"{p[0]}/{p[1]}"] = {
            "since": start.year,
            "zero-volume days (B)": (vol[p[1]].loc[start:] == 0).mean(),
            "gross/yr same close": stats(eq_g, d, w)["gross/yr"],
            "gross/yr next close": stats(eq_n, dn, w)["gross/yr"],
            "gross/yr traded days": stats(eq_t, dt, w)["gross/yr"],
            "break-even half-spread": stats(eq_t, dt, w)["break-even half-spread"],
        }
    return pd.DataFrame(rows).T


def main() -> None:
    pd.set_option("display.width", 250)
    pairs = PWB_PAIRS + OTHER_PAIRS
    bars = load_bars(sorted({s for p in pairs for s in p}))
    have = set(bars["close"].columns)
    pairs = [p for p in pairs if set(p) <= have]
    spread = half_spread(bars)
    universes = {
        "pwb7": (PWB_PAIRS, False),
        "pwb7 liquid": (PWB_PAIRS, True),
        "all liquid": (pairs, True),
    }
    rows = {}
    for uname, (up, liquid) in universes.items():
        w = weights(bars, up, liquid)
        for fill in ("same close", "next close", "next open", "traded days"):
            eq, d = simulate(bars, w, fill)
            rows[(uname, fill, "gross")] = stats(eq, d, w)
            eq, d = simulate(bars, w, fill, spread)
            rows[(uname, fill, "spread")] = stats(eq, d, w)
            for cap in (5_000, 100_000):
                eq, d = simulate(bars, w, fill, spread, capital=cap)
                rows[(uname, fill, f"spread + IBKR ${cap // 1000}k")] = stats(eq, d, w)
    df = pd.DataFrame(rows).T
    pct = [
        "CAGR",
        "vol",
        "max DD",
        "gross/yr",
        "spread cost/yr",
        "commission/yr",
        "% time invested",
    ]
    fmt = df.copy().astype(object)
    for c in df.columns:
        f = "{:+.1%}" if c in pct else ("{:.2f}" if c == "Sharpe" else "{:.0f}")
        f = "{:.2%}" if c == "break-even half-spread" else f
        fmt[c] = df[c].map(lambda v, f=f: f.format(v))
    print("=== dual-class pairs, full history (cash earns 0, no borrow fees) ===")
    print(fmt.to_string(), "\n")

    w = weights(bars, PWB_PAIRS, False)
    print("=== pwb7, same close vs next close, before and after the paper (gross) ===")
    for fill in ("same close", "next close", "traded days"):
        eq, d = simulate(bars, w, fill)
        for label, sl in (("to 2007", slice(None, PUBLISHED)), ("2008 on", slice(PUBLISHED, None))):
            s = stats(eq.loc[sl] / eq.loc[sl].iloc[0], d.loc[sl], w.loc[sl])
            print(f"  {fill:10s} {label:8s} CAGR {s['CAGR']:+.1%}  Sharpe {s['Sharpe']:.2f}")
    print("\n=== each pwb7 pair alone (no liquidity filter) ===")
    pp = per_pair(bars, PWB_PAIRS, False, spread)
    print(pp.to_string(float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
