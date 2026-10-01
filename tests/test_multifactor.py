import numpy as np
import pandas as pd
import pytest

from horizon_trader.backtest import multifactor as MF


def _prices(days=400, n=3, seed=3):
    idx = pd.bdate_range("2022-01-03", periods=days)
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.01, (days, n))
    return pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), idx, [f"T{i}" for i in range(n)])


def test_zscore_ranks_and_keeps_missing():
    s = pd.Series([3.0, 1.0, np.nan, *range(10, 50)])
    z = MF.zscore(s)
    assert pd.isna(z.iloc[2])
    assert z.iloc[1] < z.iloc[0] < z.iloc[3]
    assert z.dropna().mean() == pytest.approx(0.0)
    assert MF.zscore(pd.Series([1.0, 2.0])).isna().all()  # fewer than MIN_NAMES


def test_price_signals_have_no_lookahead():
    adj = _prices()
    full = MF.price_signals(adj)
    for t in (300, 399):
        cut = MF.price_signals(adj.iloc[: t + 1])
        for k in full:
            pd.testing.assert_series_equal(cut[k].iloc[t], full[k].iloc[t])
    rets = adj.pct_change()
    expected = -rets.iloc[399 - 251 : 400].std()
    pd.testing.assert_series_equal(full["low_vol"].iloc[399], expected, check_names=False)


def test_latest_filing_uses_only_filings_before_the_date():
    d = pd.Timestamp("2024-03-29")
    fund = pd.DataFrame(
        {
            "cik": ["1", "1", "1", "2"],
            "filed": pd.to_datetime(["2023-02-01", "2024-03-28", "2024-03-29", "2021-02-01"]),
            "period_end": pd.to_datetime(["2022-12-31", "2023-12-31", "2023-12-31", "2020-12-31"]),
            "x": [1, 2, 3, 4],
        }
    )
    got = MF.latest_filing(fund, d, "period_end")
    assert got.loc["1", "x"] == 2  # the filing dated d itself may have landed after the close
    assert "2" not in got.index  # fiscal year too old
    later = pd.concat([fund, fund.assign(filed=fund["filed"] + pd.Timedelta(days=400))])
    pd.testing.assert_frame_equal(MF.latest_filing(later, d, "period_end"), got)


def test_fundamental_signals_ratios():
    d = pd.Timestamp("2024-03-29")
    caps = pd.DataFrame(
        {"cik": ["0000000001", "2"], "market_cap": [100.0, 50.0]}, index=["AAA", "BBB"]
    )
    fund = pd.DataFrame(
        {
            "cik": ["0000000001", "0000000002"],
            "filed": pd.to_datetime(["2024-02-01", "2024-02-01"]),
            "period_end": pd.to_datetime(["2023-12-31", "2023-12-31"]),
            "equity": [20.0, 25.0],
            "net_income": [5.0, -1.0],
            "gross_profit": [30.0, np.nan],
            "assets": [60.0, 100.0],
        }
    )
    sims = pd.DataFrame(
        {
            "cik": ["0000000002"],
            "accn": ["x"],
            "filed": pd.to_datetime(["2024-02-01"]),
            "sim": [0.9],
        }
    )
    out = MF.fundamental_signals(caps, fund, sims, d)
    assert out.loc["AAA", "bm"] == 0.2 and out.loc["BBB", "bm"] == 0.5
    assert out.loc["AAA", "ep"] == 0.05 and out.loc["BBB", "ep"] == -0.02
    assert out.loc["AAA", "quality"] == 0.5 and pd.isna(out.loc["BBB", "quality"])
    assert pd.isna(out.loc["AAA", "lazy"]) and out.loc["BBB", "lazy"] == 0.9


def _table(months=20, names=60, seed=0, signal_drives_returns=True):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-31", periods=months, freq="ME")
    idx = pd.MultiIndex.from_product(
        [dates, [f"S{i}" for i in range(names)]], names=["date", "ticker"]
    )
    t = pd.DataFrame(rng.normal(size=(len(idx), len(MF.ALL))), idx, MF.ALL)
    noise = rng.normal(scale=0.5, size=len(idx))
    t["fwd"] = 0.02 * t["quality"] + noise * 0.01 if signal_drives_returns else noise
    return t


def test_ridge_learns_the_signal_that_drives_returns():
    _, w = MF.ridge_scores(_table())
    assert (w.idxmax(axis=1) == "quality").all()


def test_ridge_weights_ignore_the_future():
    t = _table()
    scores, w = MF.ridge_scores(t)
    k = 15
    d = t.index.get_level_values("date").unique()[k]
    changed = t.copy()
    later = changed.index.get_level_values("date") >= d  # returns from date k onward
    changed.loc[later, "fwd"] = -changed.loc[later, "fwd"] * 10
    scores2, w2 = MF.ridge_scores(changed)
    pd.testing.assert_series_equal(w.loc[d], w2.loc[d])
    pd.testing.assert_series_equal(scores.loc[d], scores2.loc[d])
    assert w.index.min() == t.index.get_level_values("date").unique()[MF.TRAIN_MIN_MONTHS]


def test_composite_needs_enough_signals_and_schedule_picks_the_top():
    t = _table(months=1, names=50)
    t.iloc[0, :3] = np.nan  # first name has only 2 of 5 signals
    c = MF.composite(t, MF.ALL)
    assert pd.isna(c.iloc[0]) and c.iloc[1:].notna().all()
    sched = MF.schedule_from(c, n=5)
    ((d, w),) = sched.items()
    assert list(w.index) == list(c.droplevel("date").nlargest(5).index)
    assert MF.schedule_from(c, n=30) == {}  # needs 2n names with a score
