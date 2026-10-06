import pandas as pd
import pytest

from horizon_trader.backtest.metrics import max_drawdown, summarize
from horizon_trader.backtest.sim import simulate
from horizon_trader.config import ExecutionSettings
from horizon_trader.datasources.store import load_bars
from horizon_trader.execution import ZERO_COSTS, CostModel
from horizon_trader.execution.costs import (
    CLEARING,
    FINRA_TAF,
    IBKR_PLANS,
    SEC_FEE,
    TIERED_EXCHANGE,
    ibkr_costs,
)


def test_ibkr_tiered_commission_min_per_share_and_cap():
    c = IBKR_PLANS["tiered"]
    assert c.commission(10, 100.0) == pytest.approx(0.35)  # minimum
    assert c.commission(1000, 1.0) == pytest.approx(3.5)  # per share
    assert c.commission(0.5, 10.0) == pytest.approx(0.05)  # capped at 1% of value


def test_tiered_fees_on_every_fill_and_regulatory_fees_on_sells():
    c = IBKR_PLANS["tiered"]
    buy, sell = c.fees(100, 50.0), c.fees(-100, 50.0)
    assert buy == pytest.approx(100 * (CLEARING + TIERED_EXCHANGE))
    assert sell == pytest.approx(buy + 100 * 50.0 * SEC_FEE + 100 * FINRA_TAF)
    assert c.total(-100, 50.0) == pytest.approx(0.35 + sell)


def test_ibkr_fixed_commission():
    c = ibkr_costs("fixed", slippage_bps=0)
    assert c.commission(10, 100.0) == pytest.approx(1.0)  # $1 minimum
    assert c.commission(1000, 10.0) == pytest.approx(5.0)  # $0.005/share
    assert c.fees(1000, 10.0) == 0.0  # exchange + clearing included in Fixed
    assert c.fees(-1000, 10.0) == pytest.approx(10_000 * SEC_FEE + 1000 * FINRA_TAF)
    assert c.fill_price(1, 100.0) == 100.0


def test_slippage_is_adverse_both_ways():
    c = CostModel(slippage_bps=5)
    assert c.fill_price(1, 100.0) == pytest.approx(100.05)
    assert c.fill_price(-1, 100.0) == pytest.approx(99.95)


def _panel(values):
    idx = pd.bdate_range("2021-01-04", periods=len(values))
    return pd.DataFrame({"SPY": values}, index=idx)


def test_signal_trades_next_open_and_equity_tracks_price():
    px = _panel([100.0, 110.0, 121.0])
    targets = _panel([1.0, 1.0, 1.0])
    res = simulate(targets, px, px, 1_000.0, ExecutionSettings(), ZERO_COSTS)
    # day 0: all cash; day 1: buy at the 110 open; day 2: +10%
    assert res.equity.tolist() == pytest.approx([1_000.0, 1_000.0, 1_100.0])
    assert len(res.trades) == 1


def test_costs_reduce_equity():
    px = _panel([100.0, 110.0, 121.0])
    targets = _panel([1.0, 1.0, 1.0])
    free = simulate(targets, px, px, 1_000.0, ExecutionSettings(), ZERO_COSTS)
    paid = simulate(targets, px, px, 1_000.0, ExecutionSettings(), CostModel())
    assert paid.equity.iloc[-1] < free.equity.iloc[-1]
    assert paid.trades["commission"].sum() > 0


@pytest.mark.parametrize("missing", [float("nan"), 0.0, float("inf")])
def test_missing_open_never_fills_at_a_stale_close(missing):
    closes = _panel([100.0, 110.0, 120.0])
    opens = _panel([100.0, missing, 120.0])
    targets = _panel([1.0, 1.0, 1.0])
    result = simulate(targets, opens, closes, 1_000.0, ExecutionSettings(), ZERO_COSTS)
    assert result.trades["date"].tolist() == [closes.index[2]]
    assert result.trades["price"].tolist() == [120.0]
    assert result.equity.tolist() == pytest.approx([1_000.0, 1_000.0, 1_000.0])


def test_missing_open_freezes_held_position_until_a_quote_returns():
    closes = _panel([100.0, 100.0, 110.0, 90.0])
    opens = _panel([100.0, 100.0, float("nan"), 90.0])
    targets = _panel([1.0, 0.0, 0.0, 0.0])
    result = simulate(targets, opens, closes, 1_000.0, ExecutionSettings(), ZERO_COSTS)
    assert result.trades["date"].tolist() == [closes.index[1], closes.index[3]]
    assert result.trades["quantity"].tolist() == [10.0, -10.0]
    assert result.equity.tolist() == pytest.approx([1_000.0, 1_000.0, 1_100.0, 900.0])


def test_missing_open_uses_prior_mark_to_size_other_symbols():
    closes = _panel([100.0, 100.0, 500.0])
    closes["QQQ"] = 100.0
    opens = closes.copy()
    opens.loc[closes.index[2], "SPY"] = float("nan")
    targets = pd.DataFrame({"SPY": [0.5, 0.5, 0.5], "QQQ": [0.0, 0.5, 0.5]}, index=closes.index)
    result = simulate(targets, opens, closes, 1_000.0, ExecutionSettings(), ZERO_COSTS)
    # Missing-open SPY is worth the last known $500 at this open, not $2,500
    # based on today's as-yet-unknown close; QQQ therefore receives $500.
    assert result.trades["symbol"].tolist() == ["SPY", "QQQ"]
    assert result.trades["quantity"].tolist() == [5.0, 5.0]


def test_metrics():
    eq = pd.Series([100.0, 120.0, 90.0, 130.0], index=pd.bdate_range("2021-01-04", periods=4))
    assert max_drawdown(eq) == pytest.approx(-0.25)
    doubled = pd.Series([100.0, 200.0], index=pd.to_datetime(["2020-01-01", "2021-01-01"]))
    assert summarize(doubled)["CAGR"] == pytest.approx(1.0, rel=1e-2)


def test_bar_store_caches_until_tomorrow(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    calls = []

    def source(symbols):
        calls.append(symbols)
        idx = pd.bdate_range("2021-01-04", periods=3)
        ohlcv = {"open": [1.0, 2, 3], "high": [2.0, 3, 4], "low": [0.5, 1, 2]}
        ohlcv |= {"close": [1.5, 2.5, 3.5], "volume": [100, 200, 300]}
        return {s: pd.DataFrame(ohlcv, idx) for s in symbols}

    first = load_bars(["SPY", "TLT"], source=source)
    second = load_bars(["SPY", "TLT"], start="2021-01-05", source=source)
    assert calls == [["SPY", "TLT"]]
    assert list(first["close"].columns) == ["SPY", "TLT"]
    assert len(second["open"]) == 2
