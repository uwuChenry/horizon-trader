import numpy as np
import pandas as pd
import pytest

from horizon_trader.execution.costs import FINRA_TAF, SEC_FEE
from horizon_trader.intraday import market_momentum as M

TZ = "America/New_York"


def synthetic(n_days: int = 40, seed: int = 0, half_day: int | None = None):
    """Random-walk minute bars for one ticker, in the Massive long format, plus daily bars."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2024-01-02", periods=n_days)
    minute, daily, px = [], [], 100.0
    for i, d in enumerate(days):
        n = 210 if i == half_day else M.SESSION
        px *= 1 + rng.normal(0, 0.005)  # overnight gap
        steps = rng.normal(0, 0.0008, n)
        close = px * np.cumprod(1 + steps)
        open_ = np.r_[px, close[:-1]]
        ts = pd.Timestamp(d).tz_localize(TZ) + pd.Timedelta(hours=9.5)
        minute.append(
            pd.DataFrame(
                {
                    "ts": ts + pd.to_timedelta(np.arange(n), "min"),
                    "ticker": "SPY",
                    "open": open_,
                    "high": np.maximum(open_, close) * 1.0002,
                    "low": np.minimum(open_, close) * 0.9998,
                    "close": close,
                    "volume": rng.integers(1_000, 5_000, n).astype(float),
                    "date": pd.Timestamp(d),
                }
            )
        )
        daily.append({"date": pd.Timestamp(d), "open": px, "close": close[-1]})
        px = close[-1]
    return pd.concat(minute, ignore_index=True), pd.DataFrame(daily)


def test_make_bars_layout_and_half_day():
    minute, daily = synthetic(5, half_day=2)
    minute = minute.drop(index=100)  # a missing minute on day 0 (j = 100)
    stray = minute[minute["date"] == daily["date"][2]].tail(1)  # a print in the 13:00 minute
    stray = stray.assign(ts=stray["ts"] + pd.Timedelta(minutes=1))
    minute = pd.concat([minute, stray], ignore_index=True)
    b = M.make_bars(minute, daily)
    assert b.close.shape == (5, M.SESSION)
    assert b.daily["session_len"].tolist() == [390, 390, 210, 390, 390]
    day0 = minute[minute["date"] == daily["date"][0]]
    assert b.close.iloc[0, 100] == day0["close"].iloc[99]  # forward-filled
    assert b.fill.iloc[0, 100] == day0["close"].iloc[99]  # no open: last close
    assert b.fill.iloc[0, 101] == day0["open"].iloc[100]
    assert np.isnan(b.close.iloc[2, 250])  # after a half day's close
    assert b.daily["prev_close"].iloc[1] == daily["close"].iloc[0]


def test_noise_targets_rule():
    price = [101.0, 99.0, 100.5, 101.0, 99.0, np.nan]
    upper = [100.8, 100.8, 100.8, 100.8, 100.8, 100.8]
    lower = [99.2, 99.2, 99.2, 99.2, 99.2, 99.2]
    vwap = [100.0, 100.0, 100.0, 101.5, 98.0, 100.0]
    # above band & VWAP, below both, inside, above band but below VWAP, below band but above VWAP
    assert M.noise_targets(price, upper, lower, vwap).tolist() == [1, -1, 0, 0, 0, 0]
    assert M.noise_targets([101.0], [np.nan], [np.nan], [100.0]).tolist() == [0]


def test_day_trades_entries_reversals_and_close():
    fill = np.arange(390, dtype=float)  # price = bar index, so fills are easy to read
    checks = M.CHECKS[:4]  # 29, 59, 89, 119
    t = M.day_trades([1, 1, -1, 0], checks, fill, 500.0, 390, "d", "noise")
    assert [(x["side"], x["entry_idx"], x["exit_idx"], x["exit_reason"]) for x in t] == [
        (1, 30, 90, "signal"),
        (-1, 90, 120, "signal"),
    ]
    assert t[0]["entry_px"] == 30 and t[0]["exit_px"] == 90  # the bar after the check
    t = M.day_trades([0, 0, 0, -1], checks, fill, 500.0, 390, "d", "noise")
    assert t[0]["exit_px"] == 500.0 and t[0]["exit_reason"] == "close"
    # on a half day, checks at or after the close are skipped
    assert M.day_trades([0, 0, 1, 1], checks, fill, 500.0, 90, "d", "noise") == []


def test_noise_sigma_matches_definition():
    minute, daily = synthetic(20)
    b = M.make_bars(minute, daily)
    s = M.noise_sigma(b.close, b.daily["open"])
    move = (b.close.div(b.daily["open"], axis=0) - 1).abs()
    assert s.iloc[16, 59] == pytest.approx(move.iloc[2:16, 59].mean())
    assert s.iloc[:12].isna().all().all()  # needs 12 of 14 days of history


def test_late_trades_sides():
    minute, daily = synthetic(20, half_day=5)
    b = M.make_bars(minute, daily)
    rod = M.late_trades(b, "rod").set_index("date")
    d = b.close.index[3]
    ret = b.close.loc[d, 359] / b.daily.loc[d, "prev_close"] - 1
    assert rod.loc[d, "side"] == np.sign(ret) and rod.loc[d, "entry_idx"] == 360
    assert rod.loc[d, "exit_px"] == b.daily.loc[d, "close"]
    half = b.close.index[5]
    assert rod.loc[half, "entry_idx"] == 180  # 12:30 on a 13:00 close
    long = M.late_trades(b, "long")
    assert (long["side"] == 1).all() and len(long) == len(b.close) - 1  # day 0 has no prev close


@pytest.mark.parametrize("build", [M.noise_trades, M.late_trades])
def test_trades_ignore_the_future(build):
    """Cutting off (or changing) later days never changes the trades of earlier days."""
    minute, daily = synthetic(40, seed=3)
    full = build(M.make_bars(minute, daily))
    cut = daily["date"][29]
    short = build(M.make_bars(minute[minute["date"] <= cut], daily[daily["date"] <= cut]))
    pd.testing.assert_frame_equal(full[full["date"] <= cut].reset_index(drop=True), short)
    other_m, other_d = synthetic(40, seed=99)  # different future
    mixed_m = pd.concat([minute[minute["date"] <= cut], other_m[other_m["date"] > cut]])
    mixed_d = pd.concat([daily[daily["date"] <= cut], other_d[other_d["date"] > cut]])
    mixed = build(M.make_bars(mixed_m, mixed_d))
    pd.testing.assert_frame_equal(mixed[mixed["date"] <= cut].reset_index(drop=True), short)
    assert len(full[full["date"] <= cut]) > 0


def test_run_portfolio_sizing_costs_and_slippage():
    days = pd.bdate_range("2024-01-01", periods=20)
    closes = 100 * np.cumprod(1 + np.tile([0.01, -0.01], 10))
    daily = pd.DataFrame({"open": 100.0, "close": closes}, index=days)
    vol = M.daily_vol(daily).iloc[-1]  # ~1.0%, so a 2% target wants ~2x
    d = days[-1]
    trades = pd.DataFrame(
        [M._trade(d, 1, 30, 100.0, 90, 101.0, "signal", "x"),
         M._trade(d, -1, 90, 101.0, 390, 100.0, "close", "x")]
    )  # fmt: skip
    acct = M.Account(equity=10_000.0, plan="paper", slippage=0.01)
    equity, fills = M.run_portfolio(trades, daily, acct, days[-1:])
    qty = np.floor(10_000 * min(4.0, 0.02 / vol) / 100.0)
    assert fills["qty"].eq(qty).all() and 150 <= qty <= 250
    assert fills["entry_fill"].tolist() == [100.01, 100.99]  # slippage against us on entries
    assert fills["exit_fill"].tolist() == [100.99, 100.0]  # none on the market-on-close exit
    assert fills["costs"].tolist() == pytest.approx([2 * 0.0035 * qty] * 2)
    gross = qty * (100.99 - 100.01) + qty * (100.99 - 100.0)
    assert equity.iloc[-1] == pytest.approx(10_000 + gross - 4 * 0.0035 * qty)

    capped = M.run_portfolio(trades, daily, M.Account(10_000.0, vol_target=1.0), days[-1:])[1]
    assert capped["qty"].iloc[0] == 400  # 4x cap
    fixed = M.run_portfolio(
        trades, daily, M.Account(10_000.0, vol_target=None, leverage=1.0), days[-1:]
    )[1]
    assert fixed["qty"].iloc[0] == 100


def test_ibkr_fixed_minimum_dominates_small_orders():
    days = pd.bdate_range("2024-01-01", periods=20)
    daily = pd.DataFrame({"open": 600.0, "close": 600.0 * (1 + np.r_[0, 0.01] .repeat(10))},
                         index=days)  # fmt: skip
    trades = pd.DataFrame([M._trade(days[-1], 1, 360, 600.0, 390, 601.0, "close", "x")])
    acct = M.Account(5_000.0, plan="fixed", slippage=0.0, vol_target=None, leverage=1.0)
    fills = M.run_portfolio(trades, daily, acct, days[-1:])[1]
    assert fills["qty"].iloc[0] == 8
    sell_fees = 8 * 601.0 * SEC_FEE + 8 * FINRA_TAF
    assert fills["costs"].iloc[0] == pytest.approx(2.0 + sell_fees)  # $1 minimum each way


def test_bundle_trades_times():
    days = pd.bdate_range("2024-01-01", periods=20)
    daily = pd.DataFrame({"open": 100.0, "close": 100 * (1 + np.r_[0, 0.01].repeat(10))},
                         index=days)  # fmt: skip
    trades = pd.DataFrame([M._trade(days[-1], 1, 30, 100.0, 390, 101.0, "close", "x")])
    fills = M.run_portfolio(trades, daily, M.Account(10_000.0), days[-1:])[1]
    b = M.bundle_trades(fills, "SPY")
    assert b["entry_time"].iloc[0] == pd.Timestamp(days[-1]).tz_localize(TZ) + pd.Timedelta(
        hours=10
    )
    assert b["exit_time"].iloc[0].hour == 16
