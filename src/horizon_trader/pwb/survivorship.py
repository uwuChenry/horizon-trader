"""How much of the site's long-only stock results is survivorship? ("today's S&P 500 since 1990")

    uv run python -m horizon_trader.pwb.survivorship

About a quarter of the audited strategies (Most Diversified Portfolio, Kelly, 1/N, risk
parity, shrinkage optimisers, ...) hold names from today's S&P 500, including ABNB, in a NAV
that starts in 1990. A stock only makes today's index by having done well, so any long-only
portfolio of today's members, back-tested, starts with a head start.

Measured here with monthly rebalancing, weights set at each month-end close:
  EW survivors   equal weight in every current S&P 500 member that had a price that month
  MDP survivors  the Most Diversified Portfolio (Choueifaty & Coignard 2008,
                 https://doi.org/10.3905/JPM.2008.35.1.40): long-only weights maximising
                 sum(w * vol) / portfolio vol, from the previous 252 days of daily returns
                 (covariance shrunk 10% toward its diagonal for stability). The site ranks its
                 replication of the follow-up paper at Sharpe 1.49
  RSP            Invesco's equal-weight S&P 500 ETF (from 2003-05): the point-in-time version
                 of "EW survivors", with real index changes, delistings and a 0.20% fee
  S&P 500 TR     cap-weighted index with dividends
The gap between EW survivors and RSP is what the universe alone adds. No trading costs anywhere.
Current members come from github.com/datasets/s-and-p-500-companies (updated weekly).
"""

from __future__ import annotations

import io
import time
import urllib.request

import numpy as np
import pandas as pd

from horizon_trader.config import data_dir
from horizon_trader.data.store import load_bars
from horizon_trader.pwb.audit import tbill_monthly

MEMBERS_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
)
COV_DAYS, SHRINK = 252, 0.10


def current_members() -> list[str]:
    path = data_dir() / "reference" / "sp500_members.csv"
    if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86_400:
        with urllib.request.urlopen(MEMBERS_URL, timeout=60) as resp:
            df = pd.read_csv(io.BytesIO(resp.read()))
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
    df = pd.read_csv(path)
    return sorted(df["Symbol"].str.replace(".", "-", regex=False))


def mdp_weights(cov: np.ndarray, iters: int = 3000, tol: float = 1e-10) -> np.ndarray:
    """Long-only Most Diversified Portfolio. Solves min y'Cy - 2 s'y, y >= 0 (s = vols) by
    accelerated projected gradient; w = y / sum(y) maximises the diversification ratio."""
    s = np.sqrt(np.diag(cov))
    step = 1.0 / (2 * np.linalg.eigvalsh(cov)[-1])
    y = z = s / s.sum()
    t = 1.0
    for _ in range(iters):
        y_new = np.maximum(z - step * (2 * cov @ z - 2 * s), 0.0)
        t_new = (1 + np.sqrt(1 + 4 * t * t)) / 2
        z = y_new + (t - 1) / t_new * (y_new - y)
        if np.abs(y_new - y).max() < tol:
            y = y_new
            break
        y, t = y_new, t_new
    return y / y.sum()


def diversification_ratio(w: np.ndarray, cov: np.ndarray) -> float:
    return float(w @ np.sqrt(np.diag(cov)) / np.sqrt(w @ cov @ w))


def month_ends(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = index.to_series()
    return pd.DatetimeIndex(s.groupby(index.to_period("M")).max().to_numpy())


def portfolios(close: pd.DataFrame) -> pd.DataFrame:
    """Monthly returns of EW and MDP on the given universe. Weights use data up to the
    month-end close they're set at; the return is the next month's."""
    ends = month_ends(close.index)
    mclose = close.loc[ends]
    fwd = mclose.pct_change(fill_method=None).shift(-1)  # next month's return per stock
    daily = close.pct_change(fill_method=None)
    rows = {}
    for t in ends[:-1]:
        live = mclose.loc[t].notna() & fwd.loc[t].notna()
        names = live[live].index
        r_next = fwd.loc[t, names]
        ew = r_next.mean()
        mdp = np.nan
        window = daily.loc[:t].iloc[-COV_DAYS:][names]
        full = window.columns[window.notna().all()]
        if len(window) == COV_DAYS and len(full) >= 20:
            cov = window[full].cov().to_numpy() * 252
            cov = (1 - SHRINK) * cov + SHRINK * np.diag(np.diag(cov))
            w = mdp_weights(cov)
            mdp = float(w @ r_next[full].to_numpy())
        rows[t] = {"EW survivors": ew, "MDP survivors": mdp, "names": len(names)}
    out = pd.DataFrame(rows).T
    # label each return by the month it is earned in
    out.index = out.index + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(1)
    return out.dropna(subset=["EW survivors"])


def stats(m: pd.Series, rf: pd.Series, market: pd.Series) -> dict[str, float]:
    m = m.dropna()
    eq = (1 + m).cumprod()
    years = len(m) / 12
    vol = m.std() * np.sqrt(12)
    rf = rf.reindex(m.index).ffill().fillna(0.0)
    mk = market.reindex(m.index)
    return {
        "CAGR": eq.iloc[-1] ** (1 / years) - 1,
        "vol": vol,
        "Sharpe": m.mean() * 12 / vol,
        "Sharpe excess": (m - rf).mean() * 12 / vol,
        "max DD": (eq / eq.cummax() - 1).min(),
        "beta": m.cov(mk) / mk.var(),
    }


def main() -> None:
    pd.set_option("display.width", 250)
    members = current_members()
    bars = load_bars(members + ["RSP", "^SP500TR"])
    close = bars["close"]
    bench = close[["RSP", "^SP500TR"]]
    stocks = close[[c for c in members if c in close.columns]].loc["1989-01-01":]
    print(f"{stocks.shape[1]} of {len(members)} current members have prices")
    port = portfolios(stocks)
    bm = bench.loc[month_ends(bench.index)].pct_change(fill_method=None)
    bm.index = bm.index + pd.offsets.MonthEnd(0)
    monthly = port.join(bm.rename(columns={"^SP500TR": "S&P 500 TR"}))
    rf = tbill_monthly()
    market = monthly["S&P 500 TR"]
    windows = {
        "1990-01 to today (the site's window)": "1990-01-31",
        "2003-06 to today (RSP exists)": "2003-06-30",
    }
    for label, start in windows.items():
        mm = monthly.loc[start:]
        cols = ["EW survivors", "MDP survivors", "RSP", "S&P 500 TR"]
        df = pd.DataFrame({c: stats(mm[c], rf, market) for c in cols if mm[c].notna().any()}).T
        out = df.copy().astype(object)
        for c in df.columns:
            f = "{:.2f}" if c in ("Sharpe", "Sharpe excess", "beta") else "{:+.1%}"
            out[c] = df[c].map(lambda v, f=f: f.format(v))
        print(f"\n=== {label} ===")
        print(out.to_string())
    print(
        f"\nmembers with a price: {int(port['names'].iloc[0])} in {port.index[0]:%Y-%m}, "
        f"{int(port['names'].iloc[-1])} in {port.index[-1]:%Y-%m}"
    )
    gap = (monthly["EW survivors"] - monthly["RSP"]).dropna()
    by_year = (1 + monthly[["EW survivors", "RSP"]].dropna()).groupby(lambda t: t.year).prod() - 1
    print("\nEW survivors minus RSP by year:")
    print(
        " ".join(
            f"{y % 100:02d}:{v:+.0%}" for y, v in (by_year.iloc[:, 0] - by_year.iloc[:, 1]).items()
        )
    )
    print(f"average gap {gap.mean() * 12:+.1%}/yr over {len(gap) / 12:.0f} years")


if __name__ == "__main__":
    main()
