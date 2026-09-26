from datetime import date

import numpy as np
import pandas as pd
import pytest

from horizon_trader.intraday import features as F
from horizon_trader.intraday import orb

A = np.array


# ---------------------------------------------------------------- simulate_trade


def test_long_trade_held_to_close():
    #          bar0   bar1   bar2
    o, h, lo = A([10.0, 10.15, 10.4]), A([10.05, 10.3, 10.6]), A([9.9, 10.15, 10.3])
    r = orb.simulate_trade(o, h, lo, o, side=1, level=10.2, stop_dist=0.1, close_px=11.0)
    assert r["entry_idx"] == 1 and r["entry_px"] == 10.2 and r["stop_px"] == pytest.approx(10.1)
    assert r["exit_px_cons"] == r["exit_px_opt"] == 11.0 and not r["stopped_cons"]


def test_never_triggered_returns_none():
    o, h, lo = A([10.0, 10.1]), A([10.1, 10.15]), A([9.9, 10.0])
    assert orb.simulate_trade(o, h, lo, o, 1, 10.2, 0.1, 11.0) is None


def test_gap_through_level_fills_at_open():
    o, h, lo = A([10.5]), A([10.6]), A([10.45])
    r = orb.simulate_trade(o, h, lo, o, 1, level=10.2, stop_dist=0.1, close_px=11.0)
    assert r["entry_px"] == 10.5  # worse than the level: a stop order becomes a market order


def test_same_bar_ambiguity_cons_vs_opt():
    # entry bar spans both the level (10.2) and the stop (10.1): order unknown within the minute
    o, h, lo = A([10.15, 10.3]), A([10.25, 10.4]), A([10.05, 10.2])
    r = orb.simulate_trade(o, h, lo, o, 1, level=10.2, stop_dist=0.1, close_px=11.0)
    assert r["stopped_cons"] and r["exit_px_cons"] == pytest.approx(10.1)
    assert not r["stopped_opt"] and r["exit_px_opt"] == 11.0


def test_path_mode_uses_bar_direction():
    # entry bar: open 10.15 below the 10.2 level, low 10.05 below the 10.1 stop
    o, h, lo = A([10.15, 10.3]), A([10.25, 10.4]), A([10.05, 10.2])
    up = A([10.22, 10.35])  # up bar: open-low-high-close, so the dip came before the entry
    r = orb.simulate_trade(o, h, lo, up, 1, level=10.2, stop_dist=0.1, close_px=11.0)
    assert not r["stopped_path"] and r["exit_px_path"] == 11.0
    down = A([10.08, 10.35])  # down bar: open-high-low-close, so the dip came after
    r = orb.simulate_trade(o, h, lo, down, 1, level=10.2, stop_dist=0.1, close_px=11.0)
    assert r["stopped_path"] and r["exit_px_path"] == pytest.approx(10.1)
    # an up bar that closes back through a tighter stop is stopped in the entry minute too
    r = orb.simulate_trade(o, h, lo, A([10.155, 10.35]), 1, 10.2, 0.04, 11.0)  # stop 10.16
    assert r["stopped_path"]


def test_stop_gap_exits_at_open_not_stop():
    o, h, lo = A([10.2, 9.8]), A([10.25, 9.9]), A([10.15, 9.7])
    r = orb.simulate_trade(o, h, lo, o, 1, level=10.2, stop_dist=0.1, close_px=11.0)
    assert r["exit_idx_opt"] == 1 and r["exit_px_opt"] == 9.8  # gapped below the 10.1 stop


def test_short_mirrors_long():
    o, h, lo = A([10.0, 9.85, 9.6]), A([10.1, 9.85, 9.7]), A([9.95, 9.75, 9.5])
    r = orb.simulate_trade(o, h, lo, o, side=-1, level=9.8, stop_dist=0.1, close_px=9.0)
    assert r["entry_idx"] == 1 and r["entry_px"] == 9.8 and r["stop_px"] == pytest.approx(9.9)
    assert r["exit_px_cons"] == 9.0 and not r["stopped_cons"]


# ---------------------------------------------------------------- split-safe features


def _split_panels(n: int = 30, split_day: int = 20):
    """Flat $100 stock (range $2, 1M shares/day) that splits 2-for-1 before row split_day."""
    idx = pd.bdate_range("2024-01-01", periods=n)
    scale = np.where(np.arange(n) < split_day, 1.0, 0.5)
    close = pd.DataFrame({"X": 100 * scale}, index=idx)
    panels = {
        "open": close,
        "close": close,
        "high": close + scale[:, None],
        "low": close - scale[:, None],
        "volume": pd.DataFrame({"X": 1e6 / scale}, index=idx),
    }
    splits = pd.DataFrame(
        {"ticker": ["X"], "execution_date": [idx[split_day]], "split_from": [1], "split_to": [2]}
    )
    return panels, F.split_factors(idx, close.columns, splits)


def test_split_does_not_distort_atr_or_volume():
    panels, factor = _split_panels()
    f = F.daily_features(panels, factor, lookback=14)
    # day 25's window spans the split; in day-25 shares the range is $1 and volume 2M
    assert f["atr"]["X"].iloc[25] == pytest.approx(1.0)
    assert f["avg_volume"]["X"].iloc[25] == pytest.approx(2e6)
    assert f["atr"]["X"].iloc[18] == pytest.approx(2.0)  # before the split, old basis
    assert f["prev_close"]["X"].iloc[20] == pytest.approx(50.0)  # yesterday in today's shares


def test_split_does_not_fake_relative_volume():
    panels, factor = _split_panels()
    or_vol = panels["volume"] * 0.05  # opening range is 5% of the day, before and after
    rv = F.relative_volume(or_vol, factor, panels["volume"] > 0, lookback=14)
    assert np.allclose(rv["X"].iloc[14:], 1.0)  # would be 2.0 around the split if unadjusted


def test_features_have_no_lookahead():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2024-01-01", periods=60)
    close = pd.DataFrame(100 + rng.normal(0, 1, (60, 3)).cumsum(0), idx, list("ABC"))
    panels = {"open": close, "close": close, "high": close + 1, "low": close - 1}
    panels["volume"] = pd.DataFrame(rng.integers(1e5, 1e6, (60, 3)), idx, list("ABC"))
    splits = pd.DataFrame(
        {"ticker": ["A"], "execution_date": [idx[50]], "split_from": [1], "split_to": [3]}
    )
    full = F.daily_features(panels, F.split_factors(idx, close.columns, splits))
    or_vol = panels["volume"] * 0.1
    rv_full = F.relative_volume(or_vol, F.split_factors(idx, close.columns, splits), or_vol > 0)
    for t in (20, 40, 49):  # cut off the future (including the later split): row t must not move
        cut = idx[: t + 1]
        fac = F.split_factors(cut, close.columns, splits)
        part = F.daily_features({k: v.loc[cut] for k, v in panels.items()}, fac)
        for k in ("atr", "avg_volume", "prev_close"):
            pd.testing.assert_series_equal(part[k].iloc[t], full[k].iloc[t])
        rv = F.relative_volume(or_vol.loc[cut], fac, or_vol.loc[cut] > 0)
        pd.testing.assert_series_equal(rv.iloc[t], rv_full.iloc[t])


# ---------------------------------------------------------------- opening range and selection


def test_opening_range_requires_the_930_bar():
    day = date(2024, 3, 1)
    t0 = F.session_open(day)
    ts = [
        t0 - pd.Timedelta(minutes=1),
        t0,
        t0 + pd.Timedelta(minutes=4),
        t0 + pd.Timedelta(5, "min"),
    ]
    bars = pd.DataFrame(
        {
            "ts": ts + [t0 + pd.Timedelta(minutes=2)],
            "ticker": ["A", "A", "A", "A", "B"],
            "open": [9, 10, 11, 99, 5],
            "high": [9, 10.5, 12, 99, 5],
            "low": [9, 9.5, 10.8, 99, 5],
            "close": [9, 10.2, 11.5, 99, 5],
            "volume": [1, 100, 200, 999, 50],
        }
    )
    r = F.opening_range(bars, day, minutes=5)
    a = r.loc["A"]
    assert (a.or_open, a.or_high, a.or_low, a.or_close, a.or_volume) == (10, 12, 9.5, 11.5, 300)
    assert a.opens_on_time and not r.loc["B", "opens_on_time"]


def test_select_candidates_filters_ranks_and_sides():
    day = pd.DataFrame(
        {
            "open": [20, 20, 4, 20, 20, 20],
            "atr": [1, 1, 1, 0.4, 1, 1],
            "avg_volume": [2e6] * 6,
            "relvol": [3.0, 5.0, 9.0, 9.0, 0.5, 4.0],
            "or_open": [10, 10, 10, 10, 10, 10],
            "or_close": [11, 9, 11, 11, 11, 10],
            "opens_on_time": [True] * 6,
        },
        index=list("ABCDEF"),
    )  # C: price < $5, D: ATR too small, E: relvol < 1, F: doji
    c = orb.select_candidates(day, orb.OrbRules(keep=10))
    assert list(c.index) == ["B", "A"] and list(c["rank"]) == [1, 2] and list(c["side"]) == [-1, 1]


# ---------------------------------------------------------------- portfolio


def _one_trade(**kw) -> pd.DataFrame:
    row = {"date": pd.Timestamp("2024-03-01"), "ticker": "A", "rank": 1, "triggered": True,
           "side": 1, "entry_px": 50.0, "stop_dist": 0.25, "exit_px_cons": 51.0,
           "stopped_cons": False, "exit_px_opt": 51.0, "stopped_opt": False,
           "exit_px_path": 51.0, "stopped_path": False} | kw  # fmt: skip
    return pd.DataFrame([row])


def test_sizing_risks_one_percent_capped_by_leverage():
    acct = orb.Account(equity=10_000, top_n=1, plan="none")
    _, fills = orb.run_portfolio(_one_trade(), acct)
    # risk: 1% * 10k / 0.25 = 400 shares; leverage cap 4 * 10k / 50 = 800 shares
    assert fills.qty.iloc[0] == 400 and fills.pnl.iloc[0] == pytest.approx(400.0)
    _, fills = orb.run_portfolio(_one_trade(stop_dist=0.05), acct)
    assert fills.qty.iloc[0] == 800  # 2,000 by risk, capped by 4x leverage


def test_costs_and_slippage_reduce_pnl():
    trade = _one_trade()
    acct = orb.Account(equity=10_000, top_n=1, plan="fixed", slippage=0.01)
    equity, fills = orb.run_portfolio(trade, acct)
    # 400 shares: entry slips 1c, close exit (MOC) doesn't; 2 x $2 commission; sell fees
    sec_taf = 400 * 51.0 * orb.SEC_FEE + 400 * orb.FINRA_TAF
    assert fills.pnl.iloc[0] == pytest.approx(400 * 0.99 - 4.0 - sec_taf)
    assert equity.iloc[0] == 10_000 and equity.iloc[-1] == pytest.approx(10_000 + fills.pnl.iloc[0])


def test_unranked_and_untriggered_trades_are_ignored():
    trades = pd.concat([_one_trade(), _one_trade(rank=2), _one_trade(triggered=False)])
    _, fills = orb.run_portfolio(trades, orb.Account(top_n=1, plan="none"))
    assert len(fills) == 1


def test_calendar_keeps_flat_days_in_the_equity_curve():
    trade = _one_trade()  # one trading day only
    calendar = pd.bdate_range("2024-02-28", "2024-03-05")
    equity, _ = orb.run_portfolio(trade, orb.Account(top_n=1, plan="none"), calendar)
    assert len(equity) == len(calendar) + 1  # + the starting-capital point
    assert equity.loc["2024-03-04"] == equity.iloc[-1]  # flat after the trade day


@pytest.mark.parametrize("plan", ["none", "paper", "fixed", "tiered"])
def test_vectorized_costs_match_cost_model(plan):
    rng = np.random.default_rng(5)
    qty = rng.integers(1, 5000, 200).astype(float)
    entry, exit_ = rng.uniform(1, 500, 200), rng.uniform(1, 500, 200)
    side = rng.choice([1, -1], 200)
    model = orb.PLANS[plan]
    expected = [
        model.total(q * s, a) + model.total(-q * s, b)
        for q, a, b, s in zip(qty, entry, exit_, side, strict=True)
    ]
    np.testing.assert_allclose(orb.trade_costs(qty, entry, exit_, side, plan), expected, rtol=1e-12)


def test_candidate_bars_cache_matches_the_minute_file(tmp_path, monkeypatch):
    from horizon_trader.data import massive

    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    day = date(2024, 3, 1)
    t0 = F.session_open(day)
    ts = [t0 + pd.Timedelta(minutes=m) for m in (-5, 0, 1, 7, 400)]  # pre-market, RTH, after close
    bars = pd.DataFrame({"ts": ts * 2, "ticker": ["A"] * 5 + ["B"] * 5, "open": np.arange(10.0),
                         "high": np.arange(10.0) + 1, "low": np.arange(10.0) - 1,
                         "close": np.arange(10.0), "volume": 100, "transactions": 1})  # fmt: skip
    path = massive.local_path("minute", day)
    path.parent.mkdir(parents=True)
    bars.to_parquet(path, index=False)
    trades = pd.DataFrame({"date": [pd.Timestamp(day)], "ticker": ["A"]})

    cand = orb.CandidateBars(trades, minutes=5)
    session = cand.session(pd.Timestamp(day), "A")
    assert list(session["open"]) == [1.0, 2.0, 3.0]  # 9:30, 9:31, 9:37 only
    assert list(cand.after_or(pd.Timestamp(day), "A")["open"]) == [3.0]  # from 9:35
    assert cand.session(pd.Timestamp(day), "B").empty  # not a candidate
    again = orb.CandidateBars(trades, minutes=5)  # second load comes from the cache
    pd.testing.assert_frame_equal(again.session(pd.Timestamp(day), "A"), session)


def test_dollar_volume_floor_filters_before_the_top_n_cut():
    day = pd.DataFrame(
        {"open": [20.0] * 4, "atr": [1.0] * 4, "avg_volume": [2e6, 2e6, 9e6, 2e6],
         "prev_close": [20.0, 20.0, 50.0, 20.0], "relvol": [9.0, 8.0, 3.0, 2.0],
         "or_open": [10.0] * 4, "or_close": [11.0] * 4, "opens_on_time": [True] * 4},
        index=list("ABCD"),
    )  # fmt: skip
    # dollar volume: A, B, D = $40M; C = $450M. With keep=1 and no floor, A wins.
    assert list(orb.select_candidates(day, orb.OrbRules(keep=1)).index) == ["A"]
    big = orb.OrbRules(keep=1, min_dollar_volume=100e6)
    assert list(orb.select_candidates(day, big).index) == ["C"]  # ranked 3rd on relvol, kept


def test_candidate_bars_fetch_new_tickers_on_days_already_cached(tmp_path, monkeypatch):
    from horizon_trader.data import massive

    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    day = date(2024, 3, 1)
    t0 = F.session_open(day)
    bars = pd.DataFrame({"ts": [t0, t0], "ticker": ["A", "B"], "open": [1.0, 2.0],
                         "high": [1.0, 2.0], "low": [1.0, 2.0], "close": [1.0, 2.0],
                         "volume": 1, "transactions": 1})  # fmt: skip
    path = massive.local_path("minute", day)
    path.parent.mkdir(parents=True)
    bars.to_parquet(path, index=False)
    one = pd.DataFrame({"date": [pd.Timestamp(day)], "ticker": ["A"]})
    orb.CandidateBars(one, minutes=5)
    both = pd.DataFrame({"date": [pd.Timestamp(day)] * 2, "ticker": ["A", "B"]})
    cand = orb.CandidateBars(both, minutes=5)  # same day, new ticker: must be fetched
    assert list(cand.session(pd.Timestamp(day), "B")["open"]) == [2.0]
    assert list(cand.session(pd.Timestamp(day), "A")["open"]) == [1.0]
