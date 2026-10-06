"""Economic invariants: net orders, funding capacity and dividend availability."""

import pandas as pd
import pytest

from horizon_trader.backtest.shared_account import SharedAccount
from horizon_trader.execution.costs import ZERO_COSTS, CostModel
from horizon_trader.execution.observe import EvidenceLog


def test_internal_cross_does_not_pay_fees_or_move_cash():
    a = SharedAccount(1000, CostModel(), sleeves={"core": {"QQQ": 5}})
    a.rebalance({"core": {"QQQ": 2}, "noise": {"QQQ": 3}}, {"QQQ": 100}, "t")
    assert not a.orders
    assert a.cash == 1000
    assert a.positions() == {"QQQ": 5}


def test_net_reversal_pays_one_minimum_and_retains_sleeve_attribution():
    a = SharedAccount(1000, CostModel(min_per_order=1), sleeves={"core": {"QQQ": 2}})
    a.rebalance({"noise": {"QQQ": -4}}, {"QQQ": 100}, "t")
    assert len(a.orders) == 1
    assert a.orders[0]["quantity"] == -4
    assert a.orders[0]["fee"] == 1
    assert a.positions() == {"QQQ": -2}
    assert a.sleeves["core"]["QQQ"] == 2


def test_minimum_fee_and_slippage_reduce_whole_share_capacity():
    a = SharedAccount(1000, CostModel(min_per_order=1), gross_limit=1)
    a.rebalance({"core": {"QQQ": 10}}, {"QQQ": 100}, "t", slips={"QQQ": 0.1})
    assert a.positions() == {"QQQ": 9}
    assert a.cash == pytest.approx(98.1)
    assert a.decisions[0]["unfilled"] == 1


def test_two_orders_cannot_spend_the_same_buying_power():
    a = SharedAccount(1000, ZERO_COSTS, gross_limit=1)
    a.rebalance({"core": {"A": 8}, "orb": {"B": 8}}, {"A": 100, "B": 100}, "t")
    assert a.positions() == {"A": 8, "B": 2}
    assert a.cash == 0


def test_working_stop_entry_reserves_capacity_until_cancelled():
    a = SharedAccount(1000, ZERO_COSTS, gross_limit=1, reserved_gross=400)
    a.rebalance({"noise": {"QQQ": 10}}, {"QQQ": 100}, "t")
    assert a.positions() == {"QQQ": 6}
    a.reserved_gross = 0
    a.rebalance({"noise": {"QQQ": 10}}, {"QQQ": 100}, "next")
    assert a.positions() == {"QQQ": 10}


def test_no_short_allows_hedge_only_to_flat():
    a = SharedAccount(500, ZERO_COSTS, allow_short=False, sleeves={"core": {"QQQ": 5}})
    a.rebalance({"noise": {"QQQ": -10}}, {"QQQ": 100}, "t")
    assert a.positions() == {}
    assert a.sleeves == {"core": {"QQQ": 5}, "noise": {"QQQ": -5}}


def test_dividend_receivable_is_nav_but_not_cash_and_only_pays_once():
    day, pay = pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-05")
    a = SharedAccount(0, ZERO_COSTS, gross_limit=1, sleeves={"core": {"QQQ": 10}})
    a.dividend(day, "QQQ", 10, pay, withholding=0.3)
    assert a.equity({"QQQ": 100}) == 1070
    a.rebalance({"core": {"QQQ": 11}}, {"QQQ": 100}, day)
    assert a.positions()["QQQ"] == 10
    a.settle(pay)
    a.settle(pay)
    assert a.cash == 70
    assert a.receivables == []


def test_split_preserves_economic_value_and_future_dividend_share_count():
    a = SharedAccount(500, ZERO_COSTS, sleeves={"core": {"A": 10}})
    before = a.equity({"A": 100})
    a.split("A", 2)
    assert a.equity({"A": 50}) == before
    assert a.positions()["A"] == 20


def test_zero_net_request_does_not_invent_liquidation_after_drift():
    a = SharedAccount(-500, ZERO_COSTS, gross_limit=1, sleeves={"core": {"A": 10}})
    a.rebalance({"core": {"A": 5}, "noise": {"A": 5}}, {"A": 100}, "t")
    assert not a.orders
    assert a.positions()["A"] == 10


def test_risk_reduction_allowed_after_drift_and_invalid_price_rejected():
    a = SharedAccount(-900, ZERO_COSTS, gross_limit=2, sleeves={"core": {"A": 10}})
    a.rebalance({"core": {"A": 5}}, {"A": 100}, "t")
    assert a.positions()["A"] == 5
    with pytest.raises(ValueError, match="invalid mark"):
        a.rebalance({"core": {"A": 3}}, {"A": float("nan")}, "t")


def test_evidence_log_append_strict_json_and_missing_quotes(tmp_path):
    import json

    log = EvidenceLog(tmp_path)
    log.write("quote", bid=float("nan"), ask=10.0, valid_two_sided=False)
    log.write("execution", execution_id="test")
    rows = [json.loads(line) for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]["bid"] is None
    assert rows[0]["observed_utc"].endswith("+00:00")
    assert rows[0]["run_id"] == rows[1]["run_id"]


def test_delayed_orb_uses_unfilled_candidates_and_resimulates_exit():
    import runpy
    from pathlib import Path

    import numpy as np

    module = runpy.run_path(
        str(Path(__file__).parents[1] / "research/shared_account_2026_10_01/replay.py")
    )
    inputs = module["Inputs"].__new__(module["Inputs"])
    day = pd.Timestamp("2024-01-02")
    inputs.events = {}
    inputs.noise = {}
    inputs.orb = pd.DataFrame(index=pd.DatetimeIndex([]))  # baseline had no filled trade
    inputs.top = pd.DataFrame(
        [dict(ticker="A", side=1, level=100.0, atr=10.0, close=98.0)], index=[day]
    )
    bars = pd.DataFrame(dict(minute=np.arange(20), ticker="A", open=100.0, high=101.0, low=99.0))
    bars.loc[12, "low"] = 80.0
    inputs.session = lambda d: dict(frame=bars, length=20)
    events = inputs.day_events(day, 5)
    entry = [(key, e) for key, values in events.items() for e in values if e["target"] == ("A", 1)]
    exit_ = [(key, e) for key, values in events.items() for e in values if e["target"] == ("A", 0)]
    assert entry[0][0][0] == 11  # order placed at minute 10, next-minute trade-through
    assert exit_[0][0][0] == 12
    assert exit_[0][1]["price"] == 90  # stop based on new entry, not a baseline exit


def test_historical_share_basis_and_split_day_dividend():
    import runpy
    from pathlib import Path

    module = runpy.run_path(
        str(Path(__file__).parents[1] / "research/shared_account_2026_10_01/replay.py")
    )
    frame = pd.DataFrame(
        {
            "Open": [50.0, 50.0],
            "Close": [50.0, 50.0],
            "Dividends": [1.0, 1.0],
            "Stock Splits": [0.0, 2.0],
        },
        index=pd.date_range("2024-01-01", periods=2),
    )
    raw = module["historical_raw"](frame)
    assert raw.open.tolist() == [100.0, 50.0]
    assert raw.dividend.tolist() == [2.0, 1.0]
