import pandas as pd
import pytest

from horizon_trader.config import ExecutionSettings
from horizon_trader.execution import PaperBroker, compute_orders

PRICES = {"SPY": 500.0, "TLT": 100.0, "GLD": 200.0}
EXEC = ExecutionSettings(min_trade_value=25, share_decimals=4)


def test_orders_move_positions_to_targets():
    broker = PaperBroker(cash=5_000.0)
    targets = pd.Series({"SPY": 0.6, "TLT": 0.4})
    for o in compute_orders(targets, broker.positions(), PRICES, broker.equity(PRICES), EXEC):
        broker.submit(o, PRICES[o.symbol])
    pos = broker.positions()
    assert pos["SPY"] == pytest.approx(6.0)
    assert pos["TLT"] == pytest.approx(20.0)
    assert broker.cash == pytest.approx(0.0)


def test_untargeted_holdings_are_sold_and_sells_come_first():
    orders = compute_orders(
        pd.Series({"SPY": 0.5}), {"GLD": 10.0}, PRICES, equity=2_000.0, settings=EXEC
    )
    assert [o.symbol for o in orders] == ["GLD", "SPY"]
    assert orders[0].quantity == pytest.approx(-10.0)


def test_dust_trades_are_skipped():
    orders = compute_orders(pd.Series({"SPY": 0.5}), {"SPY": 4.99}, PRICES, 5_000.0, EXEC)
    assert orders == []  # 0.01 share * $500 = $5 < $25


def test_small_drift_inside_band_is_not_traded():
    held = {"SPY": 5.9}  # 5.9 * 500 / 5000 = 59% vs 60% target
    assert compute_orders(pd.Series({"SPY": 0.6}), held, PRICES, 5_000.0, EXEC) == []
    orders = compute_orders(pd.Series({"SPY": 0.7}), held, PRICES, 5_000.0, EXEC)
    assert orders[0].quantity == pytest.approx(1.1)


def test_full_exit_ignores_band():
    orders = compute_orders(pd.Series(dtype=float), {"SPY": 0.1}, PRICES, 5_000.0, EXEC)
    assert orders[0].quantity == pytest.approx(-0.1)  # 1% of equity, still closed out
