import pandas as pd
import pytest

from horizon_trader.backtest import bundle


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))


def _run():
    idx = pd.bdate_range("2024-01-01", periods=5)
    equity = pd.Series([100.0, 101, 99, 102, 103], index=idx)
    t0 = pd.Timestamp("2024-01-02 09:35", tz="America/New_York")
    trades = pd.DataFrame(
        {
            "entry_time": [t0],
            "exit_time": [t0 + pd.Timedelta(hours=6)],
            "symbol": ["X"],
            "side": [1],
            "qty": [10.0],
            "entry_px": [10.0],
            "exit_px": [10.5],
            "gross": [5.0],
            "costs": [2.0],
            "pnl": [3.0],
            "R": [0.5],
        }  # fmt: skip
    )
    return equity, trades


def test_save_and_load_roundtrip():
    equity, trades = _run()
    path = bundle.save_run("My Run!", equity, trades, {"strategy": "test"}, equity * 2)
    run = bundle.load_run(path.name)
    pd.testing.assert_series_equal(run.equity, equity, check_names=False, check_freq=False)
    pd.testing.assert_frame_equal(run.trades, trades)
    assert run.benchmark.iloc[0] == 200.0
    assert run.meta["name"] == "My Run!" and run.meta["strategy"] == "test"
    assert run.meta["start"] == "2024-01-01" and "git_commit" in run.meta
    assert path.name.endswith("_my-run")
    listed = bundle.list_runs()
    assert list(listed.run_id) == [path.name] and listed.name.iloc[0] == "My Run!"


def test_same_second_saves_do_not_collide():
    equity, trades = _run()
    a = bundle.save_run("x", equity, trades)
    b = bundle.save_run("x", equity, trades)
    assert a != b and len(bundle.list_runs()) == 2


def test_rejects_trades_missing_columns():
    equity, trades = _run()
    with pytest.raises(ValueError, match="pnl"):
        bundle.save_run("x", equity, trades.drop(columns="pnl"))
