"""Large-cap momentum on Alpaca paper (execution/momentum_book.py), with a fake Alpaca."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from horizon_trader.backtest.winners import momentum
from horizon_trader.execution import momentum_book as MB
from horizon_trader.execution.alpaca_broker import LegFill, OrderInfo
from horizon_trader.execution.ibkr_broker import GuardError
from horizon_trader.execution.ledger import Ledger

NY = "America/New_York"


def test_formation_is_the_last_session_of_the_previous_month():
    idx = pd.bdate_range("2026-10-01", "2026-11-04")
    assert MB.formation_date(idx, date(2026, 11, 5)) == pd.Timestamp("2026-10-30")
    idx = pd.bdate_range("2026-11-01", "2026-11-30")
    assert MB.formation_date(idx, date(2026, 12, 1)) == pd.Timestamp("2026-11-30")


def panel(n_names=30, days=MB.HISTORY, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-11-04", periods=days)
    drift = np.linspace(-0.002, 0.003, n_names)
    rets = rng.normal(drift, 0.01, (days, n_names))
    cols = [f"S{i:02d}" for i in range(n_names)]
    return pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx, columns=cols)


def test_ranking_is_the_backtests_momentum():
    adj = panel()
    d = MB.formation_date(adj.index, date(2026, 11, 5))
    ranking = MB.rank(adj, list(adj.columns), d)
    want = momentum(adj, MB.LOOKBACK, MB.SKIP).loc[d].nlargest(10).index
    assert list(MB.targets_from_ranking(ranking).index) == list(want)
    assert MB.targets_from_ranking(ranking).sum() == pytest.approx(1.0)
    with pytest.raises(ValueError):
        MB.targets_from_ranking(ranking.head(15))


SPLITS = pd.DataFrame({"ticker": ["S01", "S02"],
                       "execution_date": pd.to_datetime(["2026-11-05", "2026-11-20"]),
                       "split_from": [1.0, 1.0], "split_to": [4.0, 8.0]})  # fmt: skip


def test_prices_are_in_todays_share_basis():
    close = panel(5)
    px = MB.last_prices(close, ["S01", "S02"], SPLITS, date(2026, 11, 5))
    assert px["S01"] == pytest.approx(close["S01"].iloc[-1] / 4)  # split this morning
    assert px["S02"] == pytest.approx(close["S02"].iloc[-1])  # announced, not executed
    with pytest.raises(GuardError):
        MB.last_prices(close, ["NOPE"])


def test_splits_scale_the_ledger_once(tmp_path):
    led = Ledger(name="m", cash=0.0, holdings={"S01": 2.0}, root=tmp_path)
    assert MB.apply_splits(led, SPLITS, date(2026, 11, 4)) == []  # first run starts the clock
    assert MB.apply_splits(led, SPLITS, date(2026, 11, 5)) == ["S01 2026-11-05 x4"]
    assert led.holdings["S01"] == 8.0
    assert MB.apply_splits(led, SPLITS, date(2026, 11, 6)) == []
    assert led.holdings["S01"] == 8.0


class FakeAlpaca:
    def __init__(self):
        self.orders, self.sent, self.held = {}, [], {}
        self.whole = set()

    def account(self):
        return {"account": "PA7"}

    def positions(self):
        return dict(self.held)

    def session(self, day):
        return None if pd.Timestamp(day).weekday() >= 5 else ("09:30", "16:00")

    def asset(self, symbol):
        return {"tradable": True, "fractionable": symbol not in self.whole}

    def order(self, cid):
        return self.orders.get(cid)

    def submit(self, spec):
        self.sent.append(spec)
        leg = spec.legs[0]
        info = OrderInfo(spec.client_id, "accepted", 0.0, None, None,
                         [LegFill(leg.symbol, leg.side, 0.0, None)])  # fmt: skip
        self.orders[spec.client_id] = info
        return info

    def open_fill(self, prices):
        for cid, o in list(self.orders.items()):
            if o.status == "accepted":
                spec = next(s for s in self.sent if s.client_id == cid)
                leg = spec.legs[0]
                q = spec.qty if leg.side == "buy" else -spec.qty
                self.held[leg.symbol] = self.held.get(leg.symbol, 0.0) + q
                self.orders[cid] = OrderInfo(cid, "filled", spec.qty, prices[leg.symbol],
                                             "2026-11-05 09:30:01")  # fmt: skip


def data(adj):
    caps = pd.DataFrame({"ticker": [], "date": [], "name": []})
    return {"adj": adj, "close": adj, "open": adj, "universe": list(adj.columns), "caps": caps,
            "formation": MB.formation_date(adj.index, date(2026, 11, 5)),
            "splits": SPLITS.iloc[:0]}  # fmt: skip


BEFORE_OPEN = pd.Timestamp("2026-11-05 08:05", tz=NY)


def test_run_sends_the_top_10_once_then_books_fills(tmp_path):
    api, d = FakeAlpaca(), data(panel())
    api.whole = {"S29"}
    targets, orders = MB.run(api=api, root=tmp_path, now=BEFORE_OPEN, data=d)
    assert len(api.sent) == 10 and all(s.legs[0].side == "buy" for s in api.sent)
    assert {s.legs[0].symbol for s in api.sent} == set(targets.index)
    whole = [s for s in api.sent if s.legs[0].symbol == "S29"]
    assert whole and float(whole[0].qty).is_integer()
    MB.run(api=api, root=tmp_path, now=BEFORE_OPEN, data=d)  # rerun: nothing new
    assert len(api.sent) == 10
    api.open_fill(d["close"].iloc[-1].to_dict())
    nxt = d | {"adj": d["adj"]}  # same signal date, so still nothing new after booking
    MB.run(api=api, root=tmp_path, now=BEFORE_OPEN, data=nxt)
    led = Ledger.load(MB.LEDGER, MB.STARTING_CASH, tmp_path)
    assert len(led.holdings) == 10 and led.pending == []
    assert (Ledger.directory(MB.LEDGER, tmp_path) / "picks.csv").exists()


def test_refuses_during_market_hours_and_stale_data(tmp_path):
    api, d = FakeAlpaca(), data(panel())
    with pytest.raises(SystemExit, match="market is open"):
        MB.run(api=api, root=tmp_path, now=pd.Timestamp("2026-11-05 11:00", tz=NY), data=d)
    stale = d | {"adj": d["adj"].iloc[:-1], "close": d["close"].iloc[:-1]}
    with pytest.raises(GuardError, match="download it first"):
        MB.run(api=api, root=tmp_path, now=BEFORE_OPEN, data=stale)
    assert api.sent == []
