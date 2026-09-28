from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from horizon_trader.data import massive
from horizon_trader.intraday import features as F
from horizon_trader.intraday import orb

DAY = date(2024, 3, 5)


def _bars(path_after_or: list[float], ticker: str) -> pd.DataFrame:
    """390 session minutes: a 5-minute up candle from 10.0 to 10.4 (range 9.9-10.5), then a
    piecewise path; each bar spans +/- 0.05 around its close."""
    start = F.session_open(DAY)
    first = pd.DataFrame(
        {"open": [10.0, 10.1, 10.2, 10.3, 10.3], "close": [10.1, 10.2, 10.3, 10.3, 10.4],
         "high": [10.2, 10.3, 10.5, 10.4, 10.45], "low": [9.9, 10.0, 10.1, 10.2, 10.25]}
    )  # fmt: skip
    closes = np.interp(np.arange(385), np.linspace(0, 384, len(path_after_or)), path_after_or)
    opens = np.r_[10.4, closes[:-1]]
    rest = pd.DataFrame(
        {"open": opens, "close": closes, "high": np.maximum(opens, closes) + 0.05,
         "low": np.minimum(opens, closes) - 0.05}
    )  # fmt: skip
    b = pd.concat([first, rest], ignore_index=True)
    b.insert(0, "ts", [start + pd.Timedelta(minutes=i) for i in range(390)])
    return b.assign(ticker=ticker, volume=1_000.0, transactions=10)


@pytest.fixture
def orb_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    winner = _bars([10.4, 10.8, 11.5, 12.0], "WIN")  # breaks 10.5, runs to the close
    loser = _bars([10.4, 10.7, 10.0, 9.5], "LOSE")  # breaks 10.5, then falls through the stop
    session = pd.concat([winner, loser], ignore_index=True)
    path = massive.local_path("minute", DAY)
    path.parent.mkdir(parents=True)
    session.to_parquet(path, index=False)
    cands = pd.DataFrame(
        {"rank": [1, 2], "relvol": [30.0, 12.0], "side": [1, 1], "atr": [0.5, 0.5],
         "open": [10.0, 10.0], "prev_close": [9.8, 9.8], "close": [12.0, 9.5],
         "or_high": [10.5, 10.5], "or_low": [9.9, 9.9]},
        index=["WIN", "LOSE"],
    )  # fmt: skip
    rules = orb.OrbRules(stop_atr=1.0)
    trades = orb.simulate_day(session, cands, DAY, rules)
    orb._save(trades, "orb5_stop1_trades")
    return trades


def test_trade_path_maps_the_simulated_trade_back_to_clock_times(orb_data):
    from horizon_trader.dashboard import orb_view as V

    t = V.load_trades("orb5_stop1_trades")
    table = V.day_table(t, pd.Timestamp(DAY), top_n=1)
    assert list(table["taken"]) == [True, False]
    win = table.iloc[0]
    p = V.trade_path(win, V.session_bars(DAY, "WIN"))
    assert p["or_high"] == 10.5 and p["or_low"] == 9.9
    assert p["entry_px"] == pytest.approx(10.5) and p["stop_px"] == pytest.approx(10.0)
    assert p["exit_time"] == F.session_open(DAY) + orb.CLOSE_TIME  # held to the close
    assert p["exit_reason"].startswith("close") and p["exit_px"] == 12.0
    lose = table.iloc[1]
    q = V.trade_path(lose, V.session_bars(DAY, "LOSE"))
    assert q["exit_reason"] == "stop" and q["exit_px"] <= q["stop_px"] + 1e-9
    assert q["entry_time"] < q["exit_time"] < F.session_open(DAY) + orb.CLOSE_TIME


def test_size_trade_matches_the_backtest_accounting(orb_data):
    from horizon_trader.dashboard import orb_view as V

    t = V.load_trades("orb5_stop1_trades")
    for top_n in (1, 2):
        acct = orb.Account(equity=5_000.0, top_n=top_n, plan="tiered", slippage=0.02)
        _, fills = orb.run_portfolio(t, acct)
        for _, f in fills.iterrows():
            row = t[t["ticker"] == f["ticker"]].iloc[0]
            p = V.trade_path(row, V.session_bars(DAY, f["ticker"]))
            s = V.size_trade(row, p, top_n, slippage=0.02)
            assert s["shares"] == f["qty"]
            assert s["net $"] == pytest.approx(f["pnl"])


def test_day_figure_draws_candles_range_box_and_trade(orb_data):
    from horizon_trader.dashboard import orb_view as V

    t = V.load_trades("orb5_stop1_trades")
    row = V.day_table(t, pd.Timestamp(DAY), 1).iloc[0]
    b = V.session_bars(DAY, "WIN")
    fig = V.day_figure(b, row, V.trade_path(row, b), "WIN")
    kinds = [tr.type for tr in fig.data]
    assert kinds.count("candlestick") == 1 and kinds.count("bar") == 1
    names = " ".join(tr.name or "" for tr in fig.data)
    assert "entry 09:" in names and "exit 16:00" in names and "stop 10.00" in names
    assert any(s.type == "rect" for s in fig.layout.shapes)


def test_orb_day_page_renders(orb_data):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    page = Path(__file__).resolve().parents[1] / "src/horizon_trader/dashboard/orb_day.py"
    at = AppTest.from_file(str(page), default_timeout=60).run()
    assert not at.exception
    assert "ORB day" in at.title[0].value
    assert any("Bought" in m.value for m in at.markdown)
