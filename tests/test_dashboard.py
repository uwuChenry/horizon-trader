from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from horizon_trader.backtest import bundle  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "src/horizon_trader/dashboard/app.py"


@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2023-01-02", periods=300)
    equity = pd.Series(10_000 * np.cumprod(1 + rng.normal(0.0005, 0.01, 300)), index=idx)
    t0 = pd.Timestamp("2023-01-03 09:40", tz="America/New_York")
    n = 120
    pnl = rng.normal(5, 40, n)
    trades = pd.DataFrame(
        {
            "entry_time": [t0 + pd.Timedelta(days=2 * i) for i in range(n)],
            "exit_time": [t0 + pd.Timedelta(days=2 * i, hours=3) for i in range(n)],
            "symbol": rng.choice(["AAA", "BBB", "CCC"], n),
            "side": rng.choice([1, -1], n),
            "qty": 100.0,
            "entry_px": 50.0,
            "exit_px": 50.0 + pnl / 100,
            "gross": pnl + 2,
            "costs": 2.0,
            "pnl": pnl,
            "R": pnl / 50,
            "exit_reason": rng.choice(["stop", "close"], n),
            "mae_R": rng.uniform(0, 1, n),
            "mfe_R": rng.uniform(0, 2, n),
            "relvol": rng.uniform(1, 40, n),
            "rank": 1,
        }
    )
    meta = {"strategy": "test", "oos_start": "2023-09-01", "caveats": ["synthetic data"]}
    bundle.save_run("synthetic A", equity, trades, meta, equity * 1.01)
    bundle.save_run("synthetic B", equity * 1.1, trades.head(10), meta | {"strategy": "other"})
    return tmp_path


def test_dashboard_renders_every_tab_without_errors(results):
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "synthetic B"  # newest run first
    assert len(at.tabs) == 6 and len(at.metric) >= 8
    at.sidebar.selectbox[0].select_index(1).run()  # switch runs
    assert not at.exception and at.title[0].value == "synthetic A"
    at.radio[0].set_value("R").run()  # P&L in R units
    assert not at.exception


def test_dashboard_without_runs_explains_how_to_make_them(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception and "--save" in at.info[0].value


def test_trade_chart_for_daily_trade(tmp_path, monkeypatch):
    from horizon_trader.dashboard import charts

    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    idx = pd.bdate_range("2024-01-01", periods=200)
    px = pd.Series(np.linspace(100, 120, 200), index=idx)
    (tmp_path / "bars").mkdir()
    pd.DataFrame({"open": px, "high": px + 1, "low": px - 1, "close": px}).to_parquet(
        tmp_path / "bars" / "SPY.parquet"
    )
    trade = pd.Series(
        {
            "symbol": "SPY",
            "entry_time": idx[100],
            "exit_time": idx[110],
            "entry_px": 110.0,
            "exit_px": 111.0,
            "pnl": 10.0,
            "exit_reason": "x",
        }
    )
    bars = charts.trade_bars(trade, "daily")
    assert bars.index[0] >= idx[100] - pd.Timedelta(days=40) and len(bars) < 200
    fig = charts.trade_figure(trade, bars, "t")
    assert len(fig.data) == 2 and fig.data[1].marker.color == charts.WIN
    assert charts.trade_bars(trade.copy().replace({"SPY": "NOPE"}), "daily").empty
