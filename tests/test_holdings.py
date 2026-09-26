from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from horizon_trader.backtest import bundle
from horizon_trader.backtest import winners as W
from horizon_trader.dashboard import holdings_view as H

CAL = pd.bdate_range("2024-01-01", periods=10)


def test_bundle_round_trips_extra_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    eq = pd.Series(1.0, index=CAL)
    trades = pd.DataFrame(columns=bundle.TRADE_COLUMNS)
    tab = pd.DataFrame({"date": CAL[:2], "ticker": ["A", "B"], "weight": [0.5, 0.5]})
    path = bundle.save_run("with tables", eq, trades, tables={"holdings": tab})
    run = bundle.load_run(path.name)
    pd.testing.assert_frame_equal(run.tables["holdings"], tab)
    assert bundle.has_table(path.name, "holdings") and not bundle.has_table(path.name, "picks")
    plain = bundle.save_run("no tables", eq, trades)
    assert bundle.load_run(plain.name).tables == {}


def test_holdings_history_rebuilds_positions_from_fills():
    closes = pd.DataFrame({"A": np.linspace(10, 19, 10), "B": 20.0}, index=CAL)
    fills = pd.DataFrame(
        {
            "date": [CAL[1], CAL[1], CAL[5], CAL[5]],
            "symbol": ["A", "B", "A", "B"],
            "quantity": [10.0, 5.0, -10.0, 2.0],  # A sold out on day 5, B topped up
            "price": 0.0,
            "commission": 0.0,
        }
    )
    eq = pd.Series(300.0, index=CAL)
    h = W.holdings_history(fills, closes, eq)
    assert set(h.loc[h["date"] == CAL[0], "ticker"]) == set()  # nothing before the first fill
    d1 = h[h["date"] == CAL[1]].set_index("ticker")
    assert d1.at["A", "shares"] == 10 and d1.at["A", "value"] == 10 * 11.0
    assert d1.at["B", "weight"] == pytest.approx(5 * 20 / 300)
    d5 = h[h["date"] == CAL[5]].set_index("ticker")
    assert list(d5.index) == ["B"] and d5.at["B", "shares"] == 7  # sold-out A disappears


def _data(n_days=300):
    idx = pd.bdate_range("2022-01-03", periods=n_days)
    growth = {"A": 0.004, "B": 0.003, "C": 0.002, "D": 0.001, "E": -0.001, "F": 0.005}
    adj = pd.DataFrame({t: 100 * (1 + g) ** np.arange(n_days) for t, g in growth.items()}, idx)
    ends = [idx[280], idx[299]]
    caps = pd.DataFrame(
        [
            {"ticker": t, "date": d, "market_cap": 1e9 * (i + 1), "cik": t, "name": f"{t} Inc"}
            for d in ends
            for i, t in enumerate(growth)
        ]
    )
    return {"adj": adj, "ends": ends, "caps": caps}


def test_picks_table_matches_the_schedule(monkeypatch):
    monkeypatch.setattr(W, "UNIVERSE", 5)  # the smallest (A) drops out of the universe
    data = _data()
    sched = W.schedules(data, 252, 21, 2)
    picks = W.picks_table(data, 252, 21, 2, top=4)
    for d, w in sched.items():
        p = picks[picks["formation"] == d]
        assert set(p.loc[p["selected"], "ticker"]) == set(w.index)
        assert list(p["rank"]) == [1, 2, 3, 4] and "A" not in set(p["ticker"])
    assert picks.iloc[0]["ticker"] == "F" and picks.iloc[0]["name"] == "F Inc"


def _holdings():
    rows = []
    for i, d in enumerate(CAL):
        if i >= 1:
            rows.append({"date": d, "ticker": "A", "shares": 1.0, "price": 10.0 + i})
        if 2 <= i <= 4 or i >= 7:
            rows.append({"date": d, "ticker": "B", "shares": 2.0, "price": 20.0})
    h = pd.DataFrame(rows)
    h["value"] = h["shares"] * h["price"]
    h["weight"] = h["value"] / 100.0
    return h


def test_entry_dates_and_holding_periods():
    held = H.held_matrix(_holdings(), CAL)
    entry = H.entry_dates(held)
    assert entry.at[CAL[9], "A"] == CAL[1]
    assert entry.at[CAL[8], "B"] == CAL[7]  # the second holding of B, not the first
    assert pd.isna(entry.at[CAL[5], "B"])
    p = H.holding_periods(held)
    b = p[p["ticker"] == "B"]
    assert list(zip(b["start"], b["end"], strict=True)) == [(CAL[2], CAL[4]), (CAL[7], CAL[9])]


def test_positions_at_and_rebalance_helpers():
    h = _holdings()
    eq = pd.Series(100.0, index=CAL)
    picks = pd.DataFrame(
        {
            "formation": [CAL[0]] * 2 + [CAL[6]] * 2,
            "rank": [1, 2, 1, 2],
            "ticker": ["A", "C", "B", "A"],
            "name": ["A Inc", "C Inc", "B Inc", "A Inc"],
            "momentum": [0.5, 0.4, 0.6, 0.3],
            "market_cap": 1e9,
            "selected": [True, False, True, True],
        }
    )
    pos = H.positions_at(h, eq, CAL[8], picks)
    assert list(pos.index) == ["B", "A"]  # biggest weight first
    assert pos.at["A", "held since"] == CAL[1] and pos.at["A", "trading days held"] == 8
    assert pos.at["A", "move since bought"] == pytest.approx(18 / 11 - 1)
    assert pos.at["B", "rank"] == 1 and pos.at["B", "name"] == "B Inc"
    assert H.formation_for(picks, CAL[6]) == CAL[0]  # formed at the close, held from the next day
    assert H.formation_for(picks, CAL[7]) == CAL[6]
    assert H.rebalance_changes(picks, CAL[6]) == {"bought": ["B"], "sold": [], "kept": ["A"]}
    assert H.positions_at(h, eq, CAL[0], picks).empty
    assert H.snap(CAL, pd.Timestamp("2024-01-06")) == pd.Timestamp("2024-01-05")  # Saturday


def test_holdings_page_renders_and_moves_through_time(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    page = Path(__file__).resolve().parents[1] / "src/horizon_trader/dashboard/holdings.py"
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception and at.info  # no runs yet: a hint, not a crash

    eq = pd.Series(np.linspace(100, 120, 10), index=CAL)
    picks = pd.DataFrame(
        {
            "formation": [CAL[0], CAL[6]],
            "rank": [1, 1],
            "ticker": ["A", "B"],
            "name": ["A Inc", "B Inc"],
            "momentum": [0.5, 0.6],
            "market_cap": 1e9,
            "selected": [True, True],
        }
    )
    meta = {"strategy": "test", "how_it_works": "**Rule**: synthetic."}
    tables = {"holdings": _holdings(), "picks": picks}
    trades = pd.DataFrame(columns=bundle.TRADE_COLUMNS)
    bundle.save_run("synthetic holdings", eq, trades, meta, eq, tables)
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "synthetic holdings"
    assert at.metric[3].value == "2"  # A and B held on the last day
    at.slider[0].set_value(CAL[5].date()).run()
    assert not at.exception and at.metric[3].value == "1"
    at.button[0].click().run()  # jump back to the previous rebalance's trading day
    assert not at.exception and at.metric[0].value == str(CAL[1].date())
    at.button[1].click().run()  # and forward to the next one (formed CAL[6], traded CAL[7])
    assert not at.exception and at.metric[0].value == str(CAL[7].date())
