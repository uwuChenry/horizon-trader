import numpy as np
import pandas as pd
import pytest

from horizon_trader.backtest import analytics as A


def _eq(values, start="2024-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def _trades(pnls, R=None):
    t0 = pd.Timestamp("2024-01-02 09:35")
    n = len(pnls)
    df = pd.DataFrame(
        {
            "entry_time": [t0 + pd.Timedelta(days=i) for i in range(n)],
            "exit_time": [t0 + pd.Timedelta(days=i, hours=2) for i in range(n)],
            "symbol": "X",
            "side": [1, -1] * (n // 2) + [1] * (n % 2),
            "qty": 10,
            "entry_px": 10.0,
            "exit_px": 10.0,
            "pnl": pnls,
        }
    )
    df["costs"] = 1.0
    df["gross"] = df["pnl"] + df["costs"]
    if R is not None:
        df["R"] = R
    return df


def test_drawdown_periods_depth_length_and_recovery():
    eq = _eq([100, 110, 99, 88, 110, 120, 108, 120, 115])
    dd = A.drawdown_periods(eq)
    first = dd.iloc[0]  # deepest: 110 -> 88 (-20%), recovered on day 4
    assert first.depth == pytest.approx(-0.2) and first.start == eq.index[1]
    assert first.trough == eq.index[3] and first.end == eq.index[4]
    assert dd.iloc[-1].end is pd.NaT or pd.isna(dd.iloc[-1].end)  # still under water at the end
    assert len(dd) == 3


def test_equity_stats_basics():
    eq = _eq([100, 110, 99, 110])
    s = A.equity_stats(eq)
    assert s["total P&L"] == 10 and s["total return"] == pytest.approx(0.10)
    assert s["max DD"] == pytest.approx(-0.1) and s["% up days"] == pytest.approx(2 / 3)
    assert s["best day"] == pytest.approx(110 / 99 - 1) and s["worst day"] == pytest.approx(-0.1)


def test_equity_stats_beta_against_itself_is_one():
    rng = np.random.default_rng(0)
    eq = _eq(100 * np.cumprod(1 + rng.normal(0, 0.01, 300)))
    s = A.equity_stats(eq, benchmark=eq)
    assert s["beta"] == pytest.approx(1.0) and s["correlation"] == pytest.approx(1.0)
    assert s["alpha/yr"] == pytest.approx(0.0, abs=1e-12)


def test_monthly_returns_compound_within_month():
    idx = pd.to_datetime(["2024-01-02", "2024-01-31", "2024-02-15", "2024-02-29"])
    eq = pd.Series([100.0, 110.0, 99.0, 121.0], index=idx)
    m = A.monthly_returns(eq)
    assert m.loc[2024, "Jan"] == pytest.approx(0.10)  # from the first value
    assert m.loc[2024, "Feb"] == pytest.approx(0.10)  # 110 -> 121
    assert m.loc[2024, "Year"] == pytest.approx(0.21)


def test_streaks_and_trade_stats():
    t = _trades([5, 5, -2, -2, -2, 3, 0, -1], R=[1, 1, -1, -1, -1, 0.5, 0, -0.5])
    s = A.streaks(t["pnl"])
    assert list(zip(s.kind, s.length, strict=True)) == [
        ("win", 2), ("loss", 3), ("win", 1), ("loss", 1)
    ]  # fmt: skip
    st = A.trade_stats(t)
    assert st["trades"] == 8 and st["win rate"] == pytest.approx(3 / 8)
    assert st["profit factor"] == pytest.approx(13 / 7)
    assert st["payoff ratio"] == pytest.approx((13 / 3) / (7 / 4))
    assert st["max win streak"] == 2 and st["max loss streak"] == 3
    assert st["expectancy R"] == pytest.approx(np.mean([1, 1, -1, -1, -1, 0.5, 0, -0.5]))
    assert st["avg holding (hours)"] == pytest.approx(2.0) and st["costs"] == 8


def test_breakdown_groups():
    t = _trades([5, -2, 3, -1])
    b = A.breakdown(t, t["side"].map({1: "long", -1: "short"}))
    assert b.loc["long", "total P&L"] == 8 and b.loc["short", "win rate"] == 0.0


def test_split_stats_assigns_trades_by_exit():
    eq = _eq(np.linspace(100, 130, 60))
    t = _trades([1.0] * 60)
    split = str(eq.index[30].date())
    table = A.split_stats(eq, t, split)
    assert list(table.columns) == [f"before {split}", f"from {split}"]
    assert table.loc["trades"].sum() == 60


def test_round_trips_fifo_partial_closes_and_open_mark():
    fills = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
            "symbol": "X",
            "quantity": [10, 10, -15, 5],
            "price": [100.0, 110.0, 120.0, 118.0],
            "commission": [1.0, 1.0, 1.5, 0.5],
        }
    )
    rt = A.round_trips(fills, marks={"X": 125.0})
    closed = rt[rt.exit_reason == "rebalance"]
    # sell 15: 10 from the first lot (+200), 5 from the second (+50)
    assert list(closed.qty) == [10, 5] and list(closed.gross) == [200.0, 50.0]
    assert closed.costs.iloc[0] == pytest.approx(1.0 + 10 * 0.1)  # its lot fee + 10/15 of 1.5
    still_open = rt[rt.exit_reason == "open at end"]
    assert list(still_open.qty) == [5, 5] and list(still_open.entry_px) == [110.0, 118.0]
    assert still_open.gross.sum() == pytest.approx(5 * 15 + 5 * 7)
    assert (rt.pnl == rt.gross - rt.costs).all()


def test_round_trips_handles_flip_to_short():
    fills = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "symbol": "X",
            "quantity": [10, -20, 10],
            "price": [100.0, 90.0, 80.0],
            "commission": [0.0, 0.0, 0.0],
        }
    )
    rt = A.round_trips(fills)
    assert list(rt.side) == [1, -1] and list(rt.gross) == [-100.0, 100.0]


def test_deflated_sharpe_penalizes_many_trials():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.0015, 0.01, 1250))  # Sharpe ~2.4, 5 years
    one = A.deflated_sharpe(r, n_trials=1, trial_sharpe_var=0.0)
    many = A.deflated_sharpe(r, n_trials=500, trial_sharpe_var=0.03**2)
    assert one["deflated sharpe (prob.)"] > 0.99
    assert many["expected max sharpe from luck (ann.)"] > 1.0
    assert many["deflated sharpe (prob.)"] < one["deflated sharpe (prob.)"]
    noise = A.deflated_sharpe(pd.Series(rng.normal(0, 0.01, 1250)), 500, 0.03**2)
    assert noise["deflated sharpe (prob.)"] < 0.5  # pure noise, best of many: not significant
