"""Gold vs the dollar: does the inverse relationship give a tradeable signal? (pre-registered)

    uv run python -m horizon_trader.macro.gold_dollar [--save]

Idea (from the owner, via an online post): gold and the dollar move inversely, so when they get
out of line ("dollar up but gold hasn't fallen yet", or the reverse) the gap should close.
The literature supports the *contemporaneous* inverse link (Capie, Mills & Wood 2005;
Pukthuanthong & Roll 2011; Reboredo 2013), and notes it is unstable (Capie et al.; the
2022-2025 central-bank buying broke it). A same-day correlation is not a strategy; it only
pays if one side leads the other or if gaps reliably close. That is what is tested here.

Data: GLD (gold) and UUP (long-dollar-index ETF), daily, adjusted, 2007-03 onward.
UUP rather than the DXY index itself: DXY settles at 17:00 ET, an hour after GLD's close, so
"DXY today predicts GLD tomorrow" would partly be DXY seeing GLD's next-day news first.

Tests, written down before running (claimed direction in brackets; signal known at close t):
  T1 lead 1d      -UUP return on day t            -> GLD open(t+1) to open(t+2)    [+]
  T2 lead 5d      -UUP return over 5 days         -> GLD next 5 days               [+]
  T3 gap 5d       -(5-day sum of GLD's residual vs the dollar) -> GLD next 5 days  [+]
                  residual = GLD return - beta * UUP return, beta from the previous 60 days
                  ("gold ran ahead of what the dollar implies, so it gives some back")
  T4 gap 20d      as T3 over 20 days          -> GLD next 20 days                  [+]
  T5 level gap    -z-score of log GLD - b * log UUP (b and the z-score from the previous
                  250 days)                   -> GLD next 20 days                  [+]

Statistic: correlation between signal and forward return (IC), t-stat with Newey-West
standard errors (lag = horizon) because forward windows overlap.
Pass rule (fixed in advance): t >= 2 in the claimed direction over 2007-2026 AND a positive IC
in both halves (2007-2016, 2017-2026). Five tests were run, so one t of 2 is weak evidence.

Trading version, reported for every test whether or not it passes: long GLD when the signal is
positive, flat otherwise, rebalanced at the test's horizon (daily, weekly or monthly), traded
at the next open through the normal backtester ($5k, IBKR Tiered, 5 bps slippage). Compared
with GLD buy-and-hold and with a random long/flat control at the same time in the market.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

from horizon_trader.backtest.metrics import summarize
from horizon_trader.backtest.sim import simulate
from horizon_trader.config import DEFAULT_CONFIG, load_settings
from horizon_trader.data.store import load_bars
from horizon_trader.execution.costs import ibkr_costs
from horizon_trader.features.price import rebalance_at

GOLD, DOLLAR = "GLD", "UUP"
HALVES = {"2007-2016": (None, "2016-12-31"), "2017-2026": ("2017-01-01", None)}


# ---------------------------------------------------------------- signals (row t uses data <= t)


def rolling_beta(y: pd.Series, x: pd.Series, window: int) -> pd.Series:
    """OLS slope of y on x over the previous `window` rows, ending at t-1 (strictly ex ante)."""
    cov = y.rolling(window).cov(x)
    return (cov / x.rolling(window).var()).shift(1)


def dollar_lead(dollar: pd.Series, days: int) -> pd.Series:
    """Minus the dollar's return over the last `days` days (dollar down -> gold up)."""
    return -dollar.pct_change(days)


def residual_gap(gold: pd.Series, dollar: pd.Series, days: int, beta_window: int = 60) -> pd.Series:
    """Minus gold's return in excess of what the dollar implied, summed over `days` days."""
    rg, rd = gold.pct_change(), dollar.pct_change()
    resid = rg - rolling_beta(rg, rd, beta_window) * rd
    return -resid.rolling(days).sum()


def level_gap(gold: pd.Series, dollar: pd.Series, window: int = 250) -> pd.Series:
    """Minus the z-score of log gold against its fitted dollar relationship (previous `window`)."""
    lg, ld = np.log(gold), np.log(dollar)
    b = rolling_beta(lg, ld, window)  # fitted on the window ending at t-1
    a = lg.rolling(window).mean().shift(1) - b * ld.rolling(window).mean().shift(1)
    spread = lg - (a + b * ld)
    past = spread.shift(1).rolling(window)
    return -(spread - past.mean()) / past.std()


@dataclass(frozen=True)
class Test:
    name: str
    horizon: int  # trading days held / forecast
    rebalance: str  # pandas period for the trading version: D, W or M


TESTS = {
    "T1 lead 1d": Test("T1 lead 1d", 1, "D"),
    "T2 lead 5d": Test("T2 lead 5d", 5, "W"),
    "T3 gap 5d": Test("T3 gap 5d", 5, "W"),
    "T4 gap 20d": Test("T4 gap 20d", 20, "M"),
    "T5 level gap": Test("T5 level gap", 20, "M"),
}


def signals(gold: pd.Series, dollar: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "T1 lead 1d": dollar_lead(dollar, 1),
            "T2 lead 5d": dollar_lead(dollar, 5),
            "T3 gap 5d": residual_gap(gold, dollar, 5),
            "T4 gap 20d": residual_gap(gold, dollar, 20),
            "T5 level gap": level_gap(gold, dollar),
        }
    )


def forward_return(opens: pd.Series, horizon: int) -> pd.Series:
    """Return from the open of t+1 to the open of t+1+horizon: tradeable after the close of t."""
    return opens.shift(-1 - horizon) / opens.shift(-1) - 1


# ---------------------------------------------------------------- statistics


def newey_west_t(x: pd.Series, lags: int) -> float:
    """t-stat of the mean of x with Newey-West (Bartlett) standard errors."""
    x = x.dropna().to_numpy(float)
    n = len(x)
    if n < 30:
        return np.nan
    e = x - x.mean()
    var = e @ e / n
    for k in range(1, lags + 1):
        var += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return x.mean() / np.sqrt(var / n) if var > 0 else np.nan


def ic_stats(signal: pd.Series, fwd: pd.Series, horizon: int) -> dict:
    """IC (Pearson correlation) and its Newey-West t-stat, via the product of z-scores."""
    both = pd.concat([signal, fwd], axis=1).dropna()
    if len(both) < 30:
        return {"n": len(both), "IC": np.nan, "t": np.nan}
    z = (both - both.mean()) / both.std()
    prod = z.iloc[:, 0] * z.iloc[:, 1]
    return {"n": len(both), "IC": float(prod.mean()), "t": newey_west_t(prod, max(horizon, 1))}


def _between(x: pd.Series, a: str | None, b: str | None) -> pd.Series:
    return x.loc[a:b]


# ---------------------------------------------------------------- trading version


def long_flat_targets(signal: pd.Series, rebalance: str) -> pd.DataFrame:
    """1.0 in GLD when the signal is positive, else flat; held between rebalance dates."""
    daily = (signal > 0).astype(float).where(signal.notna()).to_frame(GOLD)
    return daily if rebalance == "D" else rebalance_at(daily, rebalance)


def random_targets(like: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Same time in the market and rebalance dates as `like`, but random days: a control."""
    rng = np.random.default_rng(seed)
    changes = like[GOLD].diff().fillna(1).ne(0)
    blocks = changes.cumsum()
    frac = like[GOLD].mean()
    draw = pd.Series(rng.random(blocks.max() + 1) < frac).reindex(blocks.to_numpy()).to_numpy()
    return pd.DataFrame({GOLD: draw.astype(float)}, index=like.index).where(like[GOLD].notna())


def backtest(targets: pd.DataFrame, bars: dict, start: str):
    settings = load_settings(DEFAULT_CONFIG)
    return simulate(
        targets.loc[start:].fillna(0.0),
        bars["open"][[GOLD]].loc[start:],
        bars["close"][[GOLD]].loc[start:],
        settings.account.starting_cash,
        settings.execution,
        ibkr_costs("tiered", 5.0),
    )


# ---------------------------------------------------------------- report


def correlation_by_year(gold: pd.Series, dollar: pd.Series) -> pd.Series:
    r = pd.concat([gold.pct_change(), dollar.pct_change()], axis=1).dropna()
    return r.groupby(r.index.year).apply(lambda g: g.iloc[:, 0].corr(g.iloc[:, 1]))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument(
        "--save", action="store_true", help="save the trading versions for the dashboard"
    )
    args = p.parse_args()

    bars = load_bars([GOLD, DOLLAR])
    close = bars["close"][[GOLD, DOLLAR]].dropna()
    opens = bars["open"][GOLD].reindex(close.index)
    gold, dollar = close[GOLD], close[DOLLAR]
    print(f"GLD vs UUP, {close.index[0]:%Y-%m-%d} .. {close.index[-1]:%Y-%m-%d}\n")

    corr = correlation_by_year(gold, dollar)
    print("Same-day correlation of daily returns, by year (the relationship everyone cites):")
    print("  " + "  ".join(f"{y}: {c:+.2f}" for y, c in corr.items()) + "\n")

    sig = signals(gold, dollar)
    rows = []
    for name, test in TESTS.items():
        fwd = forward_return(opens, test.horizon)
        row = {"test": name, "horizon": test.horizon}
        full = ic_stats(sig[name], fwd, test.horizon)
        row |= {"IC": full["IC"], "t (NW)": full["t"], "n": full["n"]}
        for half, (a, b) in HALVES.items():
            row[f"IC {half}"] = ic_stats(
                _between(sig[name], a, b), _between(fwd, a, b), test.horizon
            )["IC"]
        row["pass"] = bool(row["t (NW)"] >= 2 and all(row[f"IC {h}"] > 0 for h in HALVES))
        rows.append(row)
    table = pd.DataFrame(rows).set_index("test")
    print("Pre-registered tests (IC = correlation of signal with the forward GLD return):")
    with pd.option_context("display.width", 200):
        print(table.round(3).to_string() + "\n")

    start = sig.dropna().index[0].strftime("%Y-%m-%d")
    bench = backtest(pd.DataFrame({GOLD: 1.0}, index=close.index), bars, start)
    runs = [("GLD buy & hold", bench, 1.0)]
    for name, test in TESTS.items():
        t = long_flat_targets(sig[name], test.rebalance)
        res = backtest(t, bars, start)
        runs.append((f"{name} long/flat", res, float(t.loc[start:, GOLD].mean())))
        ctrl = [backtest(random_targets(t, s), bars, start).equity for s in range(20)]
        sharpes = [summarize(e)["Sharpe"] for e in ctrl]
        runs.append(("  random, same time in market (median of 20)",
                     None, float(np.median(sharpes))))  # fmt: skip
    out = []
    for label, res, extra in runs:
        if res is None:
            out.append({"run": label, "Sharpe": extra})
            continue
        s = summarize(res.equity, res.trades)
        out.append(
            {"run": label, "in market": extra}
            | {k: s[k] for k in ("CAGR", "Sharpe", "max DD", "trades/yr", "commissions")}
        )
    perf = pd.DataFrame(out).set_index("run")
    fmt = {c: "{:.1%}".format for c in ("CAGR", "max DD", "in market")}
    fmt |= {"Sharpe": "{:.2f}".format, "trades/yr": "{:.0f}".format}
    fmt |= {"commissions": "${:,.0f}".format}
    print(f"Trading versions, {start} .. today, $5k IBKR Tiered, 5 bps slippage:")
    with pd.option_context("display.width", 200):
        print(perf.to_string(formatters=fmt, na_rep=""))

    if args.save:
        from horizon_trader.backtest.analytics import round_trips
        from horizon_trader.backtest.bundle import save_run

        for label, res, _ in runs:
            if res is None or label.startswith("GLD"):
                continue
            meta = {
                "strategy": "Gold vs dollar (GLD/UUP), pre-registered",
                "params": {"test": label},
                "oos_start": "2017-01-01",
                "caveats": [
                    "Five pre-registered tests on the same data; see research/gold_dollar.md.",
                    "Daily adjusted closes from yfinance; trades at the next open.",
                ],
                "benchmark": "GLD (buy & hold)",
            }
            trades = round_trips(res.trades)
            bench_px = bars["close"][GOLD].reindex(res.equity.index)
            path = save_run(f"Gold-dollar {label}", res.equity, trades, meta, bench_px)
            print("saved", path.name)


if __name__ == "__main__":
    main()
