"""Performance and trade analytics shared by the CLI reports and the dashboard.

Everything here is a pure function of an equity curve and/or a trade table, so the numbers the
dashboard shows are the same ones the tests check. Trade tables use the bundle format (see
bundle.py): one row per round trip with at least entry_time, exit_time, symbol, side, qty,
entry_px, exit_px, gross, costs, pnl. Optional: R, exit_reason, mae_R, mfe_R, and any
strategy-specific columns.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pandas as pd

from horizon_trader.features.price import TRADING_DAYS

# ---------------------------------------------------------------- equity curve


def returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def drawdown(equity: pd.Series) -> pd.Series:
    """Fraction below the running peak (0 at a new high, negative otherwise)."""
    return equity / equity.cummax() - 1


def drawdown_periods(equity: pd.Series, top: int | None = 10) -> pd.DataFrame:
    """Peak-to-recovery episodes, deepest first: start, trough, end (NaT if not recovered)."""
    dd = drawdown(equity)
    rows, start, prev = [], None, dd.index[0]
    for t, v in dd.items():
        if v < 0 and start is None:
            start = prev
        elif v == 0 and start is not None:
            rows.append((start, dd.loc[start:t].idxmin(), t))
            start = None
        prev = t
    if start is not None:
        rows.append((start, dd.loc[start:].idxmin(), pd.NaT))
    df = pd.DataFrame(rows, columns=["start", "trough", "end"])
    if df.empty:
        return df.assign(depth=[], days=[], recovery_days=[])
    df["depth"] = [dd.loc[t] for t in df["trough"]]
    last = equity.index[-1]
    df["days"] = [
        ((e if pd.notna(e) else last) - s).days for s, e in zip(df.start, df.end, strict=True)
    ]
    df["recovery_days"] = [
        (e - t).days if pd.notna(e) else np.nan for t, e in zip(df.trough, df.end, strict=True)
    ]
    df = df.sort_values("depth", ignore_index=True)
    return df.head(top) if top else df


def monthly_returns(equity: pd.Series) -> pd.DataFrame:
    """Year x month table of compounded returns, plus a full-year column."""
    month_end = equity.resample("ME").last()
    first = equity.iloc[:1].rename(lambda t: t - pd.offsets.MonthEnd(1))  # base for month one
    m = pd.concat([first, month_end]).pct_change().dropna()
    table = pd.DataFrame({"year": m.index.year, "month": m.index.month, "r": m.values})
    pivot = table.pivot(index="year", columns="month", values="r")
    pivot.columns = [pd.Timestamp(2000, c, 1).strftime("%b") for c in pivot.columns]
    pivot["Year"] = (1 + pivot.fillna(0)).prod(axis=1) - 1
    return pivot


def rolling_sharpe(equity: pd.Series, window: int = 126) -> pd.Series:
    r = returns(equity)
    return r.rolling(window).mean() / r.rolling(window).std() * np.sqrt(TRADING_DAYS)


def equity_stats(equity: pd.Series, benchmark: pd.Series | None = None) -> dict[str, float]:
    """Headline portfolio stats. Sharpe/Sortino use a 0% risk-free rate."""
    r = returns(equity)
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    downside = r[r < 0].std()
    dd = drawdown(equity)
    periods = drawdown_periods(equity, top=None)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    stats = {
        "start equity": float(equity.iloc[0]),
        "end equity": float(equity.iloc[-1]),
        "total P&L": float(equity.iloc[-1] - equity.iloc[0]),
        "total return": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "CAGR": float(cagr),
        "vol": float(r.std() * np.sqrt(TRADING_DAYS)),
        "Sharpe": float(r.mean() / r.std() * np.sqrt(TRADING_DAYS)) if r.std() else np.nan,
        "Sortino": float(r.mean() / downside * np.sqrt(TRADING_DAYS)) if downside else np.nan,
        "max DD": float(dd.min()),
        "longest DD (days)": float(periods["days"].max()) if len(periods) else 0.0,
        "Calmar": float(cagr / abs(dd.min())) if dd.min() < 0 else np.nan,
        "best day": float(r.max()),
        "worst day": float(r.min()),
        "% up days": float((r > 0).mean()),
        "skew": float(r.skew()),
        "years": float(years),
    }
    if benchmark is not None:
        b = returns(benchmark).reindex(r.index).dropna()
        x = r.reindex(b.index)
        if len(b) > 20 and b.var() > 0:
            beta = x.cov(b) / b.var()
            stats["beta"] = float(beta)
            stats["correlation"] = float(x.corr(b))
            stats["alpha/yr"] = float((x.mean() - beta * b.mean()) * TRADING_DAYS)
    return stats


# ---------------------------------------------------------------- trades


def streaks(pnl: pd.Series) -> pd.DataFrame:
    """Consecutive runs of wins (+1) or losses (-1), in trade order. Zero P&L breaks a run."""
    sign = np.sign(pnl.to_numpy())
    rows, i = [], 0
    while i < len(sign):
        j = i
        while j + 1 < len(sign) and sign[j + 1] == sign[i]:
            j += 1
        if sign[i] != 0:
            rows.append({"kind": "win" if sign[i] > 0 else "loss", "length": j - i + 1,
                         "pnl": float(pnl.iloc[i : j + 1].sum())})  # fmt: skip
        i = j + 1
    return pd.DataFrame(rows, columns=["kind", "length", "pnl"])


def trade_stats(trades: pd.DataFrame) -> dict[str, float]:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    pnl = trades["pnl"]
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    s = streaks(pnl)
    held = trades["exit_time"] - trades["entry_time"]
    stats = {
        "trades": n,
        "win rate": float((pnl > 0).mean()),
        "avg win": float(wins.mean()) if len(wins) else np.nan,
        "avg loss": float(losses.mean()) if len(losses) else np.nan,
        "payoff ratio": float(wins.mean() / -losses.mean())
        if len(wins) and len(losses)
        else np.nan,
        "profit factor": float(wins.sum() / -losses.sum()) if len(losses) else np.inf,
        "expectancy $": float(pnl.mean()),
        "largest win": float(pnl.max()),
        "largest loss": float(pnl.min()),
        "max win streak": int(s.loc[s.kind == "win", "length"].max())
        if (s.kind == "win").any()
        else 0,
        "max loss streak": int(s.loc[s.kind == "loss", "length"].max())
        if (s.kind == "loss").any()
        else 0,
        "gross P&L": float(trades["gross"].sum()),
        "costs": float(trades["costs"].sum()),
        "costs / gross profit": float(
            trades["costs"].sum() / trades.loc[trades.gross > 0, "gross"].sum()
        )
        if (trades["gross"] > 0).any()
        else np.nan,
        "avg holding (hours)": float(held.mean() / pd.Timedelta(hours=1)),
        "% long": float((trades["side"] > 0).mean()),
    }
    if "R" in trades:
        stats["expectancy R"] = float(trades["R"].mean())
    top = pnl.sort_values(ascending=False)
    if pnl.sum() > 0:
        stats["best 5% share of P&L"] = float(top.head(max(n // 20, 1)).sum() / pnl.sum())
    return stats


def breakdown(trades: pd.DataFrame, by: str | pd.Series) -> pd.DataFrame:
    """Count, win rate, total and average P&L per group (a column name or a Series)."""
    g = trades.groupby(by, observed=True)["pnl"]
    out = pd.DataFrame(
        {
            "trades": g.size(),
            "win rate": g.apply(lambda x: (x > 0).mean()),
            "total P&L": g.sum(),
            "avg P&L": g.mean(),
        }  # fmt: skip
    )
    if "R" in trades:
        out["avg R"] = trades.groupby(by, observed=True)["R"].mean()
    return out


def _naive(times: pd.Series) -> pd.Series:
    return times.dt.tz_localize(None) if times.dt.tz is not None else times


def split_stats(equity: pd.Series, trades: pd.DataFrame, split: str) -> pd.DataFrame:
    """Stats before and from `split` (e.g. the out-of-sample start), side by side.

    Trades are assigned by exit date; the second half's equity is based on the last value
    before the split, so its first day's return counts.
    """
    t0 = pd.Timestamp(split)
    before, after = equity[equity.index < t0], equity[equity.index >= t0]
    if len(before):
        after = pd.concat([before.iloc[-1:], after])
    exits = _naive(trades["exit_time"])
    parts = {
        f"before {split}": (before, trades[exits < t0]),
        f"from {split}": (after, trades[exits >= t0]),
    }
    return pd.DataFrame(
        {k: equity_stats(e) | trade_stats(t) for k, (e, t) in parts.items() if len(e) > 20}
    )


# ---------------------------------------------------------------- fills -> round trips


def round_trips(fills: pd.DataFrame, marks: dict[str, float] | None = None) -> pd.DataFrame:
    """FIFO-match fills (date, symbol, quantity, price, commission) into round trips.

    Each closed lot slice becomes one trade; commissions are split pro rata by quantity.
    Positions still open at the end are closed at `marks` (last prices) with exit_reason
    "open at end", or dropped if no mark is given.
    """
    trades = []
    for symbol, g in fills.sort_values("date", kind="stable").groupby("symbol", sort=False):
        lots: deque[list] = deque()  # [qty (signed), price, date, commission per share]
        for f in g.itertuples():
            qty, px = float(f.quantity), float(f.price)
            fee_ps = float(f.commission) / abs(qty) if qty else 0.0
            while qty and lots and np.sign(lots[0][0]) != np.sign(qty):
                lot = lots[0]
                closed = min(abs(qty), abs(lot[0]))
                side = int(np.sign(lot[0]))
                gross = side * closed * (px - lot[1])
                costs = closed * (lot[3] + fee_ps)
                trades.append(
                    (lot[2], f.date, symbol, side, closed, lot[1], px, gross, costs, "rebalance")
                )
                lot[0] -= side * closed
                qty += side * closed
                if abs(lot[0]) < 1e-9:
                    lots.popleft()
            if abs(qty) > 1e-9:
                lots.append([qty, px, f.date, fee_ps])
        if marks and symbol in marks:
            end = fills["date"].max()
            for q, p, d, fee in lots:
                side = int(np.sign(q))
                gross = side * abs(q) * (marks[symbol] - p)
                trades.append(
                    (
                        d,
                        end,
                        symbol,
                        side,
                        abs(q),
                        p,
                        marks[symbol],
                        gross,
                        abs(q) * fee,
                        "open at end",
                    )
                )
    cols = ["entry_time", "exit_time", "symbol", "side", "qty", "entry_px", "exit_px", "gross",
            "costs", "exit_reason"]  # fmt: skip
    df = pd.DataFrame(trades, columns=cols)
    df["pnl"] = df["gross"] - df["costs"]
    return df.sort_values(["exit_time", "entry_time"], ignore_index=True)
