"""How much leverage on semiconductors is too much? SMH vs SOXL vs SMH on IBKR margin.

    uv run python -m horizon_trader.backtest.leverage

Everything is $5k at IBKR Pro, dividend-adjusted daily prices (yfinance), fixed before running:
  constant   SMH at a constant 0x-5x, rebalanced every day, borrowing at IBKR Pro's rate
             (Fed funds + 1.5%, actual/360, charged on calendar days). Above 2x this is only
             possible with portfolio margin ($110k+), so it's a map of the trade-off, not an
             account you can open at $5k. A day's loss of 1/L or more wipes it out.
  margin     a real Reg T account: buy SMH with a loan up to the 2x Reg T limit, then either
             rebalance to the target on the first trading day of each month or never rebalance
             ("set and forget"). If equity falls below 25% of the position (SMH maintenance
             margin) at a close, IBKR liquidates; modelled as a forced sale back to 2x, at 5 bps
             plus an assumed extra 50 bps for selling into the drop. Real liquidations happen
             intraday and can be worse.
  SOXL       Direxion's 3x daily semis fund (from 2010), bought and held; SOXL/SMH mixes and
             SOXL plus cash rebalanced monthly, no margin. Before 2010, a synthetic SOXL: 3x
             SOXX daily minus a 0.95% expense ratio and 2x (Fed funds + 0.5%) for the fund's
             swap financing (3x SMH before SOXX's first day, 2001-07). It's checked against
             the real SOXL where both exist.
  cash       uninvested cash earns 0: IBKR pays no interest on the first $10k.
  periods    2000-06 (SMH's first day, near the dot-com top) to today; 2010-03 (SOXL's first
             day) to today; the last 5 years; and every 5-year window starting each month.
Costs: IBKR Pro Tiered commissions, 5 bps slippage. Dividends are in the prices; US
withholding tax on them (up to 30% for non-US holders) is ignored (SMH yields ~0.5%).
"""

from __future__ import annotations

import io
import urllib.request

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.config import data_dir
from horizon_trader.data.store import load_bars
from horizon_trader.execution.costs import ibkr_costs

SPREAD = 0.015  # IBKR Pro, USD loans up to $100k: benchmark (Fed funds) + 1.5%
MAINTENANCE = 0.25  # SMH maintenance margin (Reg T minimum; IBKR's house rate may be higher)
REG_T = 2.0  # max overnight leverage in a Reg T margin account
LIQUIDATION_SLIPPAGE = 0.005
CAPITAL = 5_000.0
SOXL_EXPENSE, SOXL_SWAP_SPREAD = 0.0095, 0.005
COSTS = ibkr_costs("tiered", 5.0)


def fed_funds() -> pd.Series:
    """Daily effective Fed funds rate (fraction), from FRED, cached for a day."""
    path = data_dir() / "reference" / "dff.parquet"
    today = pd.Timestamp.now().date()
    if not path.exists() or pd.Timestamp(path.stat().st_mtime, unit="s").date() != today:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"
        with urllib.request.urlopen(url, timeout=60) as resp:
            df = pd.read_csv(io.BytesIO(resp.read()), parse_dates=["observation_date"])
        path.parent.mkdir(parents=True, exist_ok=True)
        df.set_index("observation_date")["DFF"].div(100).rename("ff").to_frame().to_parquet(path)
    return pd.read_parquet(path)["ff"]


def accrual(index: pd.DatetimeIndex, annual: pd.Series) -> pd.Series:
    """Interest factor from the previous trading day to each day: the rate known on the
    previous day, times calendar days / 360 (weekends accrue too)."""
    rate = annual.reindex(index, method="ffill").shift(1)
    days = index.to_series().diff().dt.days
    return (rate * days / 360).fillna(0.0)


# ---------------------------------------------------------------- strategies


def constant_leverage(ret: pd.Series, lev: float, borrow: pd.Series) -> pd.Series:
    """Equity multiple of holding `lev` x the asset, rebalanced daily. Borrowing costs `borrow`
    (per-day factor from `accrual`); below 1x the rest is cash earning nothing. Once a day's
    loss reaches 100%, the account is gone."""
    daily = lev * ret.fillna(0.0) - max(lev - 1.0, 0.0) * borrow
    return (1 + daily).clip(lower=0.0).cumprod()


def margin_account(
    px: pd.Series,
    target: float,
    borrow: pd.Series,
    rebalance: bool,
    capital: float = CAPITAL,
    maintenance: float = MAINTENANCE,
) -> tuple[pd.Series, dict]:
    """A Reg T account holding one ETF on margin. Returns daily equity ($) and a summary:
    forced liquidations, interest paid, commissions. `borrow` is the per-day interest factor."""
    target = min(target, REG_T)
    month = px.index.to_period("M")
    first_of_month = np.r_[True, month[1:] != month[:-1]]
    shares = debt = 0.0
    out = np.empty(len(px))
    info = {"liquidations": 0, "interest $": 0.0, "commissions $": 0.0, "wiped out": False}

    def trade(value: float, price: float, forced: bool = False) -> None:
        nonlocal shares, debt
        q = value / price
        fill = COSTS.fill_price(q, price) * (1 - LIQUIDATION_SLIPPAGE if forced else 1)
        fee = COSTS.total(q, price)
        shares += q
        debt += q * fill + fee
        info["commissions $"] += fee

    for i, (p, b) in enumerate(zip(px.to_numpy(), borrow.to_numpy(), strict=True)):
        if info["wiped out"]:
            out[i] = 0.0
            continue
        if i == 0:
            debt = -capital
            spend = target * capital - COSTS.total(target * capital / p, p)  # fees included
            trade(spend / (1 + COSTS.slippage_bps / 10_000), p)
        elif debt > 0:
            interest = debt * b
            debt += interest
            info["interest $"] += interest
        value = shares * p
        equity = value - debt
        if equity <= 0:
            info["wiped out"] = True
            out[i] = 0.0
            continue
        if debt > 0 and equity < maintenance * value:  # margin call: IBKR sells
            info["liquidations"] += 1
            trade(REG_T * equity - value, p, forced=True)
        elif rebalance and i > 0 and first_of_month[i]:
            want = target * equity - value
            if abs(want) > 0.02 * equity:
                trade(want, p)
        out[i] = shares * p - debt
    return pd.Series(out, index=px.index), info


def mix(returns: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Equity multiple of a no-margin mix, reset to `weights` at each month's first close;
    whatever isn't invested is cash earning nothing. One or two orders a month, so
    commissions are left out (under $1 a month at $5k)."""
    w = pd.Series(weights, dtype=float).to_numpy()
    r = returns[list(weights)].fillna(0.0).to_numpy()
    month = returns.index.to_period("M")
    hold, cash = w.copy(), 1.0 - w.sum()
    out = np.empty(len(r))
    for i in range(len(r)):
        if i > 0:
            if month[i] != month[i - 1]:
                total = hold.sum() + cash
                hold, cash = w * total, total * (1.0 - w.sum())
            hold = hold * (1 + r[i])
        out[i] = hold.sum() + cash
    return pd.Series(out, index=returns.index)


def synthetic_3x(ret: pd.Series, ff: pd.Series) -> pd.Series:
    """Daily returns of a 3x daily fund on `ret`: 3x the move, minus the expense ratio and
    swap financing on the borrowed 2x (Fed funds + spread)."""
    idx = ret.index
    days = idx.to_series().diff().dt.days.fillna(1)
    rate = ff.reindex(idx, method="ffill").shift(1).bfill()
    cost = 2 * (rate + SOXL_SWAP_SPREAD) * days / 360 + SOXL_EXPENSE * days / 365
    return 3 * ret - cost


# ---------------------------------------------------------------- report


def stats(eq: pd.Series, info: dict | None = None) -> dict:
    eq = eq / eq.iloc[0]
    s = A.equity_stats(eq.clip(lower=1e-9))
    yearly = eq.resample("YE").last()
    year = yearly.pct_change()
    year.iloc[0] = yearly.iloc[0] - 1
    out = {
        "CAGR": s["CAGR"] if eq.iloc[-1] > 0 else -1.0,
        "Sharpe": s["Sharpe"],
        "max DD": s["max DD"],
        "worst year": year.min(),
        "$5k ->": CAPITAL * eq.iloc[-1],
    }
    if info:
        out |= {"liquidations": info["liquidations"], "interest $": info["interest $"]}
    return out


def load() -> tuple[pd.DataFrame, pd.Series]:
    close = load_bars(["SMH", "SOXX", "SOXL"])["close"]
    ff = fed_funds()
    rets = close.pct_change(fill_method=None)
    rets["SOXL*"] = synthetic_3x(rets["SOXX"], ff)
    # real SOXL when it exists, else 3x SOXX, else (before SOXX's first day) 3x SMH
    early = synthetic_3x(rets["SMH"], ff)
    rets["SOXL+"] = rets["SOXL"].where(close["SOXL"].notna(), rets["SOXL*"])
    rets["SOXL+"] = rets["SOXL+"].where(close["SOXX"].notna() | close["SOXL"].notna(), early)
    rets["price_SMH"] = close["SMH"]
    return rets, ff


def strategies(rets: pd.DataFrame, ff: pd.Series, start: str) -> tuple[dict, dict]:
    """{name: equity multiple} and {name: margin info} for every strategy from `start`."""
    r = rets.loc[start:].copy()
    r.iloc[0, : r.columns.get_loc("price_SMH")] = 0.0
    borrow = accrual(r.index, ff + SPREAD)
    real = r["SOXL"].iloc[1:].notna().all()
    soxl, tag = ("SOXL", "SOXL") if real else ("SOXL+", "SOXL (synthetic before 2010)")
    curves, infos = {}, {}
    for lev in (1.0, 1.5, 2.0, 3.0, 4.0):
        curves[f"SMH {lev:g}x, rebalanced daily"] = constant_leverage(r["SMH"], lev, borrow)
    for lev in (1.25, 1.5, 2.0):
        for reb, label in ((True, "monthly"), (False, "never rebalanced")):
            eq, info = margin_account(r["price_SMH"], lev, borrow, reb)
            name = f"SMH {lev:g}x on margin, {label}"
            curves[name], infos[name] = eq / CAPITAL, info
    curves[f"{tag}, buy and hold"] = (1 + r[soxl].fillna(0.0)).cumprod()
    mixes = {
        f"{tag} 50% + SMH 50% (~2x)": {soxl: 0.5, "SMH": 0.5},
        f"{tag} 25% + SMH 75% (~1.5x)": {soxl: 0.25, "SMH": 0.75},
        f"{tag} 33% + cash 67% (~1x)": {soxl: 1 / 3},
    }
    for name, w in mixes.items():
        curves[name] = mix(r, w)
    return curves, infos


def table(curves: dict, infos: dict) -> pd.DataFrame:
    return pd.DataFrame({k: stats(v, infos.get(k)) for k, v in curves.items()}).T


def leverage_curve(rets: pd.DataFrame, ff: pd.Series, starts: dict) -> pd.DataFrame:
    """CAGR of constant daily leverage 0-5x on SMH per period, plus the Kelly estimate of the
    growth-optimal leverage (mean excess return / variance, same daily data)."""
    out = {}
    for label, start in starts.items():
        r = rets["SMH"].loc[start:].iloc[1:]
        b = accrual(r.index, ff + SPREAD)
        years = (r.index[-1] - r.index[0]).days / 365.25
        row = {}
        for lev in np.round(np.arange(0.0, 5.01, 0.25), 2):
            end = constant_leverage(r, lev, b).iloc[-1]
            row[f"{lev:g}x"] = end ** (1 / years) - 1 if end > 0 else -1.0
        row["Kelly leverage"] = (r - b).mean() / r.var()
        out[label] = row
    return pd.DataFrame(out)


def rolling_windows(rets: pd.DataFrame, ff: pd.Series, years: int = 5) -> pd.DataFrame:
    """Every `years`-year window starting on a month's first trading day: CAGR distribution,
    share of windows that lost money, and share that were down 80%+ at some point."""
    r = rets[["SMH", "SOXL+", "price_SMH"]].dropna(subset=["SMH"])
    idx = r.index
    month = idx.to_period("M")
    starts = idx[np.r_[True, month[1:] != month[:-1]]]
    starts = starts[starts + pd.DateOffset(years=years) <= idx[-1]]
    rows = []
    for s in starts:
        w = r.loc[s : s + pd.DateOffset(years=years)].copy()
        w.iloc[0, :2] = 0.0
        b = accrual(w.index, ff + SPREAD)
        curves = {
            f"SMH {lev:g}x daily": constant_leverage(w["SMH"], lev, b) for lev in (1, 1.5, 2, 3, 4)
        }
        curves["SOXL (synthetic before 2010)"] = (1 + w["SOXL+"].fillna(0.0)).cumprod()
        for reb, label in ((True, "monthly"), (False, "never rebalanced")):
            eq, _ = margin_account(w["price_SMH"], 2.0, b, rebalance=reb)
            curves[f"SMH 2x on margin, {label}"] = eq / CAPITAL
        for name, eq in curves.items():
            end = eq.iloc[-1]
            rows.append(
                {
                    "strategy": name,
                    "CAGR": end ** (1 / years) - 1 if end > 0 else -1.0,
                    "lost money": end < 1,
                    "fell 80%+": (eq / eq.cummax()).min() <= 0.2,
                }
            )
    g = pd.DataFrame(rows).groupby("strategy", sort=False)
    return pd.DataFrame(
        {
            "windows": g.size(),
            "median CAGR": g["CAGR"].median(),
            "10th pct CAGR": g["CAGR"].quantile(0.1),
            "worst CAGR": g["CAGR"].min(),
            "% lost money": g["lost money"].mean(),
            "% fell 80%+": g["fell 80%+"].mean(),
        }
    )


def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    out = df.astype(object).copy()
    for c in df.columns:
        if c == "Sharpe":
            f = "{:.2f}"
        elif c in ("$5k ->", "interest $"):
            f = "{:,.0f}"
        elif c in ("liquidations", "windows"):
            f = "{:.0f}"
        else:
            f = "{:+.1%}"
        out[c] = df[c].map(lambda v, f=f: "-" if pd.isna(v) else f.format(v))
    return out


def main() -> None:
    pd.set_option("display.width", 250)
    rets, ff = load()
    smh0, soxl0 = rets["SMH"].first_valid_index(), rets["SOXL"].first_valid_index()
    periods = {
        f"since {smh0:%Y-%m} (SMH start, near the dot-com top)": str(smh0.date()),
        f"since {soxl0:%Y-%m} (SOXL start)": str(soxl0.date()),
        "last 5 years": str((rets.index[-1] - pd.DateOffset(years=5)).date()),
    }
    both = rets[["SOXL", "SOXL*"]].dropna()
    real, synth = (1 + both).prod() ** (252 / len(both)) - 1
    print(
        f"synthetic SOXL check {both.index[0]:%Y-%m} .. {both.index[-1]:%Y-%m}: daily return "
        f"correlation {both.corr().iloc[0, 1]:.3f}, CAGR real {real:+.1%} vs synthetic {synth:+.1%}"
    )
    print(
        f"IBKR Pro margin rate today: Fed funds {ff.iloc[-1]:.2%} + {SPREAD:.1%} = "
        f"{ff.iloc[-1] + SPREAD:.2%}\n"
    )
    for label, start in periods.items():
        curves, infos = strategies(rets, ff, start)
        print(f"=== {label}, to {rets.index[-1]:%Y-%m-%d} ===")
        print(_fmt(table(curves, infos)).to_string(), "\n")
    print("=== CAGR by constant daily leverage on SMH (Kelly = growth-optimal estimate) ===")
    lc = leverage_curve(rets, ff, periods)
    fmt = lc.map(lambda v: f"{v:+.1%}")
    fmt.loc["Kelly leverage"] = lc.loc["Kelly leverage"].map(lambda v: f"{v:.2f}x")
    print(fmt.to_string(), "\n")
    print("=== every 5-year window starting each month since SMH's start ===")
    print(_fmt(rolling_windows(rets, ff)).to_string())


if __name__ == "__main__":
    main()
