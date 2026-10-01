"""Short volatility: "Expectations and the Option Implied-Variance" on paperswithbacktest.com.

    uv run python -m horizon_trader.pwb.short_vix

The paper (Mehta 2021, https://ssrn.com/abstract=3763497) is an option-pricing model: VIX sits
above realised variance partly because investors extrapolate past returns. The site turned it
into a "cash/short VIX rule" and reports Sharpe 1.64 (1990-2026), 1.75 over 1990-2019 vs 2.23
"published". Its positions are SPX and VIX, i.e. it shorts the VIX *index*, which can't be
traded: there is no VIX spot to borrow, and VIX futures only partly follow the index.

Rules, fixed before running (signal at the close of day t, held from t to t+1):
  always       always short volatility
  VRP > 0      short only when VIX exceeds the S&P 500's realised volatility over the previous
               21 trading days (annualised, in vol points), else cash. This is the
               implied-minus-realised wedge the paper models.
Instruments:
  synthetic    -1 x the daily % change of the VIX index (what the site trades)
  short VIXY   -1 x VIXY, a fund holding 1-2 month VIX futures (from 2011), rebalanced daily
               like the old -1x ETNs (XIV). Borrow fees not modelled
  SVXY         the ETF you can actually buy: -1x short-term VIX futures until 2018-02-27,
               -0.5x since. Held long when the rule says short volatility
Cash earns nothing in the Sharpe (rf = 0, like the site) and 3 bps is charged per switch.
Everything is also shown net of T-bills, because the site's NAV earns interest on cash.

At full size the synthetic short is wiped out (VIX +116% on 2018-02-05), so the site's 2.9% vol
means a small position. "Site-sized" mirrors that: SITE_NOTIONAL (3%) of equity short, the rest
in 3-month T-bills, rebalanced daily. That reproduces the site's number; the same sizing on the
tradeable instruments shows what is left.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.datasources.store import load_bars
from horizon_trader.features.price import TRADING_DAYS
from horizon_trader.pwb.audit import tbill_monthly

SWITCH_COST = 0.0003
SITE_NOTIONAL = 0.03
RV_WINDOW = 21


def vrp_signal(vix: pd.Series, spx: pd.Series, window: int = RV_WINDOW) -> pd.Series:
    """1 when VIX > trailing realised vol of the index (both in annualised %), else 0.
    Row t uses data up to t."""
    rv = spx.pct_change(fill_method=None).rolling(window).std() * np.sqrt(TRADING_DAYS) * 100
    return (vix > rv).astype(float).where(rv.notna() & vix.notna())


def run(short_ret: pd.Series, signal: pd.Series) -> pd.Series:
    """Equity multiple of holding `short_ret` (return of the short-vol position) while the
    previous close's signal is 1, cash otherwise, paying SWITCH_COST on each change."""
    pos = signal.shift(1).fillna(0.0)
    ret = pos * short_ret.fillna(0.0) - pos.diff().abs().fillna(pos.iloc[0]) * SWITCH_COST
    return (1 + ret).clip(lower=0.0).cumprod()


def run_sized(
    short_ret: pd.Series, signal: pd.Series, notional: float, rf_daily: pd.Series
) -> pd.Series:
    """`notional` of equity in the short-vol position when the previous close's signal is 1,
    everything else (and the margin behind the short) earning T-bills."""
    pos = signal.shift(1).fillna(0.0) * notional
    ret = pos * short_ret.fillna(0.0) + rf_daily.reindex(short_ret.index).fillna(0.0)
    ret -= pos.diff().abs().fillna(pos.iloc[0]) * SWITCH_COST
    return (1 + ret).clip(lower=0.0).cumprod()


def excess_sharpe(eq: pd.Series, rf_m: pd.Series) -> float:
    m = eq.resample("ME").last().pct_change().dropna()
    ex = m - rf_m.reindex(m.index).ffill().fillna(0.0)
    return float(ex.mean() / m.std() * np.sqrt(12)) if m.std() else np.nan


def row(eq: pd.Series, rf_m: pd.Series, pos: pd.Series) -> dict[str, float]:
    eq = eq / eq.iloc[0]
    s = A.equity_stats(eq)
    worst = eq.pct_change().min()
    return {
        "CAGR": s["CAGR"] if eq.iloc[-1] > 0 else -1.0,
        "vol": s["vol"],
        "Sharpe": s["Sharpe"],
        "Sharpe excess": excess_sharpe(eq, rf_m),
        "max DD": s["max DD"],
        "worst day": worst,
        "% time short": pos.reindex(eq.index).mean(),
    }


def main() -> None:
    pd.set_option("display.width", 250)
    close = load_bars(["^VIX", "^GSPC", "VIXY", "SVXY"])["close"]
    rf_m = tbill_monthly()
    vix, spx = close["^VIX"], close["^GSPC"]
    sig = vrp_signal(vix, spx)
    inst = {
        "synthetic (short VIX index)": -vix.pct_change(fill_method=None),
        "short VIXY (futures)": -close["VIXY"].pct_change(fill_method=None),
        "long SVXY (the ETF)": close["SVXY"].pct_change(fill_method=None),
    }
    always = pd.Series(1.0, index=close.index)
    windows = {
        "1990-2019 (site's in-sample)": (
            "1990-02-01",
            "2019-12-31",
            ["synthetic (short VIX index)"],
        ),
        "1990-today": ("1990-02-01", None, ["synthetic (short VIX index)"]),
        "2011-10 to today (SVXY exists)": ("2011-10-05", None, list(inst)),
        "2018-03 to today (SVXY at -0.5x)": ("2018-03-01", None, list(inst)),
    }
    for label, (start, end, names) in windows.items():
        rows = {}
        for name in names:
            r = inst[name].loc[start:end]
            for rule, s in (("always", always), ("VRP > 0", sig)):
                s = s.reindex(r.index)
                eq = run(r, s)
                rows[(name, rule)] = row(eq, rf_m, s.shift(1))
        df = pd.DataFrame(rows).T
        out = df.copy().astype(object)
        for c in df.columns:
            f = "{:.2f}" if "Sharpe" in c else "{:+.1%}"
            out[c] = df[c].map(lambda v, f=f: f.format(v))
        print(f"=== {label} ===")
        print(out.to_string(), "\n")
    rf_d = (rf_m * 12 / TRADING_DAYS).reindex(close.index, method="bfill")
    print(f"=== site-sized: {SITE_NOTIONAL:.0%} short volatility + T-bills (VRP > 0 rule) ===")
    rows = {}
    for label, (start, end, names) in windows.items():
        for name in names:
            r = inst[name].loc[start:end]
            s = sig.reindex(r.index)
            eq = run_sized(r, s, SITE_NOTIONAL, rf_d)
            bills = run_sized(r, s * 0, 0.0, rf_d)
            rows[(label, name)] = row(eq, rf_m, s.shift(1)) | {
                "T-bills alone CAGR": bills.iloc[-1] ** (1 / A.equity_stats(bills)["years"]) - 1
            }
    df = pd.DataFrame(rows).T.drop(columns=["worst day", "% time short"])
    out = df.copy().astype(object)
    for c in df.columns:
        f = "{:.2f}" if "Sharpe" in c else "{:+.1%}"
        out[c] = df[c].map(lambda v, f=f: f.format(v))
    print(out.to_string(), "\n")
    both = pd.concat({k: v for k, v in inst.items()}, axis=1).loc["2011-10-05":].dropna()
    print("daily return correlation, 2011-10 on:")
    print(both.corr().round(2).to_string())
    print(
        "\n2018-02-05 (Volmageddon):",
        ", ".join(f"{k} {v:+.0%}" for k, v in both.loc["2018-02-05"].items()),
    )


if __name__ == "__main__":
    main()
