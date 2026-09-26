"""Combine strategies into one $5k portfolio: does adding intraday sleeves help the daily book?

    uv run python -m horizon_trader.backtest.mix [--capital 5000] [--save]

Sleeves (each simulated on ITS OWN slice of the capital, IBKR Pro Tiered, so per-order minimums
bite as they would in a small sub-account; pots are not rebalanced against each other):
  daily book     the combined daily sleeves (momentum, vol-managed, trend, mean reversion)
  ORB            Stocks-in-Play ORB baseline: top-1, 1 ATR stop, stop-limit entry, measured
                 stop-out slippage, hold to the close
  ORB candidate  ORB + relative volume >= 12 + no entries after 10:30 (chosen after earlier
                 tests on the same data, so optimistic)
  QQQ noise      noise-area intraday momentum on QQQ (market_momentum.py, the other agent's
                 replication): 2% vol target, max 4x, 0.5c slippage

Blends (pre-registered capital splits): 100% daily book (the reference), 70/30 and 50/50 daily
book / ORB, 70/30 daily book / ORB candidate, and 50/25/25 daily book / ORB / QQQ noise; plus
each intraday sleeve alone. Period 2021-11-01 .. 2026-09 (the intraday data), split at
2024-01-01. Reports the correlation of daily returns and CAGR / Sharpe / max DD per blend.
"""

from __future__ import annotations

import argparse
from datetime import time

import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.backtest import bundle
from horizon_trader.backtest import run as R
from horizon_trader.config import load_settings
from horizon_trader.intraday import market_momentum as MM
from horizon_trader.intraday import orb
from horizon_trader.intraday import orb_ideas as I

START = "2021-11-01"
SPLIT = "2024-01-01"
BLENDS = {  # name: {sleeve: share of capital}
    "daily book only (reference)": {"daily book": 1.0},
    "daily 70 / ORB 30": {"daily book": 0.7, "ORB": 0.3},
    "daily 50 / ORB 50": {"daily book": 0.5, "ORB": 0.5},
    "daily 70 / ORB candidate 30": {"daily book": 0.7, "ORB candidate": 0.3},
    "daily 50 / ORB 25 / QQQ noise 25": {"daily book": 0.5, "ORB": 0.25, "QQQ noise": 0.25},
    "ORB only": {"ORB": 1.0},
    "ORB candidate only": {"ORB candidate": 1.0},
    "QQQ noise only": {"QQQ noise": 1.0},
}
CANDIDATE = I.Idea("ORB candidate", "candidate", min_relvol=12.0, cutoff=time(10, 30))


class Sleeves:
    """Builds each sleeve's daily equity curve for any starting capital (cached per capital)."""

    def __init__(self) -> None:
        self.trades = orb.build_trades(I.RULES)
        cal = pd.DatetimeIndex(sorted(self.trades["date"].unique()))
        self.orb_cal = cal[cal >= START]
        picks = {
            i.name: I.select(self.trades, i, pd.Series(dtype=int)) for i in (I.IDEAS[0], CANDIDATE)
        }
        keys = sorted(
            {
                (r.date, r.ticker)
                for p in picks.values()
                for r in p[p["triggered"].astype(bool)].itertuples()
            }
        )
        bars = I.Bars.load(self.trades, keys)
        self.orb_sims = {
            "ORB": I.simulate(picks["baseline"], I.IDEAS[0], bars),
            "ORB candidate": I.simulate(picks["ORB candidate"], CANDIDATE, bars),
        }
        self.settings = load_settings()
        self.daily_bars = R.load_universe_bars(self.settings)
        self.daily_targets = R.target_histories(self.settings, self.daily_bars["close"])["combined"]
        self.qqq_bars, qcal, strategies = MM.build("QQQ")
        self.qqq_cal = qcal[qcal >= START]
        self.qqq_noise = strategies["noise"]
        self._cache: dict = {}

    def equity(self, sleeve: str, capital: float) -> pd.Series:
        key = (sleeve, round(capital, 2))
        if key in self._cache:
            return self._cache[key]
        if sleeve == "daily book":
            self.settings.account.starting_cash = capital
            eq = R.run_targets(self.daily_targets, self.daily_bars, START, self.settings).equity
        elif sleeve in self.orb_sims:
            acct = orb.Account(equity=capital, top_n=1, plan="tiered", slippage=None)
            sim = self.orb_sims[sleeve]
            eq, _ = orb.run_portfolio(sim[sim["date"].isin(self.orb_cal)], acct, self.orb_cal)
        elif sleeve == "QQQ noise":
            acct = MM.Account(equity=capital, plan="tiered", slippage=0.005)
            t = self.qqq_noise[self.qqq_noise["date"].isin(self.qqq_cal)]
            eq, _ = MM.run_portfolio(t, self.qqq_bars.daily, acct, self.qqq_cal)
        else:
            raise KeyError(sleeve)
        eq = eq[eq.index >= pd.Timestamp(START) - pd.Timedelta(days=7)]
        self._cache[key] = eq
        return eq


def blend(curves: dict[str, pd.Series]) -> pd.Series:
    """Sum of separate sub-account equity curves on a common calendar (flat days carried)."""
    idx = sorted(set().union(*[c.index for c in curves.values()]))
    total = sum(c.reindex(idx).ffill().bfill() for c in curves.values())
    return pd.Series(total, index=pd.DatetimeIndex(idx), name="equity")


def period_stats(equity: pd.Series) -> dict:
    out = {}
    for label, (a, b) in {
        "all": (None, None),
        "2021-23": (None, SPLIT),
        "2024-26": (SPLIT, None),
    }.items():
        e = equity
        if b is not None:
            e = e[e.index < pd.Timestamp(b)]
        if a is not None:
            before = e[e.index < pd.Timestamp(a)]
            e = pd.concat([before.iloc[-1:], e[e.index >= pd.Timestamp(a)]])
        s = A.equity_stats(e)
        out |= {
            f"{label} CAGR": s["CAGR"],
            f"{label} Sharpe": s["Sharpe"],
            f"{label} max DD": s["max DD"],
        }
    return out


OVERLAYS = {  # follow-up, NOT pre-registered: intraday sleeves on the SAME capital
    "daily book only": ["daily book"],
    "daily + ORB overlay": ["daily book", "ORB"],
    "daily + ORB candidate overlay": ["daily book", "ORB candidate"],
    "daily + QQQ noise overlay": ["daily book", "QQQ noise"],
    "daily + ORB + QQQ noise overlay": ["daily book", "ORB", "QQQ noise"],
}


def overlay(returns: pd.DataFrame, parts: list[str], capital: float) -> pd.Series:
    """Equity if every sleeve trades the SAME account: intraday sleeves are flat by the close,
    so in one margin account they can size off full equity while the daily book holds its
    positions (overnight exposure stays the daily book's). Daily returns add. Ignores the 4x
    intraday cap, which `exposure()` checks separately."""
    eq = capital * (1 + returns[parts].sum(axis=1)).cumprod()
    return pd.concat([pd.Series([capital], index=[eq.index[0] - pd.Timedelta(days=1)]), eq])


def exposure(sleeves: Sleeves, capital: float) -> dict:
    """Intraday gross exposure of each intraday sleeve, in multiples of account equity."""
    acct = orb.Account(equity=capital, top_n=1, plan="tiered", slippage=None)
    sim = sleeves.orb_sims["ORB"]
    _, f = orb.run_portfolio(sim[sim["date"].isin(sleeves.orb_cal)], acct, sleeves.orb_cal)
    eq = sleeves.equity("ORB", capital)
    orb_x = (f["qty"] * f["entry_fill"]) / f["date"].map(eq.shift(1).to_dict())
    t = sleeves.qqq_noise[sleeves.qqq_noise["date"].isin(sleeves.qqq_cal)]
    qacct = MM.Account(equity=capital, plan="tiered", slippage=0.005)
    _, qf = MM.run_portfolio(t, sleeves.qqq_bars.daily, qacct, sleeves.qqq_cal)
    q_lev = qf.groupby("date")["lev"].first()
    return {
        "ORB": (orb_x.mean(), orb_x.quantile(0.95), orb_x.max()),
        "QQQ noise": (q_lev.mean(), q_lev.quantile(0.95), q_lev.max()),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--capital", type=float, default=5_000.0)
    p.add_argument("--save", action="store_true", help="save the blends as dashboard runs")
    args = p.parse_args()

    sleeves = Sleeves()
    names = ["daily book", "ORB", "ORB candidate", "QQQ noise"]
    full = {n: sleeves.equity(n, args.capital) for n in names}
    rets = pd.DataFrame({n: e.pct_change() for n, e in full.items()}).dropna()
    spy = sleeves.daily_bars["close"]["SPY"]
    rets["SPY"] = spy.pct_change().reindex(rets.index)
    pd.set_option("display.width", 250)
    print(
        f"=== correlation of daily returns, "
        f"{rets.index[0]:%Y-%m-%d} .. {rets.index[-1]:%Y-%m-%d} ==="
    )
    print(rets.corr().round(2).to_string())

    rows, curves = [], {}
    for name, split in BLENDS.items():
        parts = {s: sleeves.equity(s, args.capital * w) for s, w in split.items()}
        eq = blend(parts)
        curves[name] = eq
        rows.append(
            {
                "blend": name,
                "capital split": ", ".join(
                    f"{s} ${args.capital * w:,.0f}" for s, w in split.items()
                ),
            }
            | period_stats(eq)
        )
    spy_eq = spy[spy.index >= pd.Timestamp(START) - pd.Timedelta(days=7)]
    rows.append(
        {"blend": "SPY buy & hold", "capital split": "-"}
        | period_stats(spy_eq / spy_eq.iloc[0] * args.capital)
    )
    table = pd.DataFrame(rows).set_index("blend")
    print(
        f"\n=== ${args.capital:,.0f} portfolio blends "
        "(each sleeve on its own sub-account, IBKR Tiered) ==="
    )
    fmt = table.copy()
    for c in fmt.columns:
        if "CAGR" in c or "max DD" in c:
            fmt[c] = fmt[c].map("{:.1%}".format)
        elif "Sharpe" in c:
            fmt[c] = fmt[c].map("{:.2f}".format)
    print(fmt.to_string())

    ov = pd.DataFrame({n: sleeves.equity(n, args.capital).pct_change() for n in names}).dropna()
    rows = []
    for name, parts in OVERLAYS.items():
        st = period_stats(overlay(ov, parts, args.capital))
        rows.append({"overlay": name} | st)
    print("\n=== follow-up (not pre-registered): intraday sleeves overlaid on the SAME capital ===")
    ot = pd.DataFrame(rows).set_index("overlay")
    for c in ot.columns:
        ot[c] = ot[c].map(("{:.1%}" if ("CAGR" in c or "max DD" in c) else "{:.2f}").format)
    print(ot.to_string())
    x = exposure(sleeves, args.capital)
    print("\nintraday gross exposure (x equity): mean / 95th pct / max")
    for k, (m, q, mx) in x.items():
        print(f"  {k:<10} {m:.2f} / {q:.2f} / {mx:.2f}")
    print("  daily book up to 1.00 (long-only). IBKR intraday cap: 4x.")
    print(f"  daily + ORB + QQQ noise at the 95th pct: {1 + x['ORB'][1] + x['QQQ noise'][1]:.2f}x")

    if args.save:
        empty = pd.DataFrame(columns=bundle.TRADE_COLUMNS)
        for name, eq in curves.items():
            meta = {
                "strategy": "portfolio blend",
                "params": BLENDS[name],
                "oos_start": SPLIT,
                "chart": "daily",
                "caveats": [
                    "Blend of separately simulated sub-accounts; trades are in each sleeve's "
                    "own run.",
                    "The ORB candidate was chosen after earlier tests on the same data.",
                ],
            }
            print(
                "saved",
                bundle.save_run(f"blend: {name}", eq, empty, meta, spy.reindex(eq.index)).name,
            )


if __name__ == "__main__":
    main()
