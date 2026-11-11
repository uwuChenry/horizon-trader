"""Option-chain logger: expiry/strike selection and a capture against a fake IB."""

import json
from datetime import date
from types import SimpleNamespace

import pandas as pd

from horizon_trader.datasources import ibkr_options_log as L


def test_select_expiries_weeklies_then_monthlies():
    exp = ["20261105", "20261106", "20261109", "20261113", "20261120", "20261127", "20261204",
           "20261218", "20270115", "20270122"]  # fmt: skip
    got = L.select_expiries(exp, date(2026, 11, 5), weeklies=4, monthlies=2)
    assert got == ["20261106", "20261109", "20261113", "20261120", "20261218", "20270115"]
    assert L.is_monthly(date(2026, 11, 20)) and not L.is_monthly(date(2026, 11, 27))


def test_select_strikes_dense_near_spot_sparse_out_to_band():
    strikes = [float(k) for k in range(50, 151)]  # $1 strikes
    got = L.select_strikes(strikes, 100.0, band=0.15, step=0.05, dense=0.025)
    assert got == [85, 90, 95, 98, 99, 100, 101, 102, 105, 110, 115]
    assert L.select_strikes([500.0], 100.0, 0.15, 0.01, 0.03) == []


class Tick(SimpleNamespace):
    def marketPrice(self):
        return self.last


class FakeIB:
    """A $1-strike chain on SPY at 100; 3 days of expiries; strike 99 doesn't list for 1113."""

    def __init__(self):
        self.lines, self.max_lines, self.types = 0, 0, []

    def reqMarketDataType(self, t):
        self.types.append(t)

    def qualifyContracts(self, *cs):
        out = []
        for i, c in enumerate(cs):
            if getattr(c, "strike", None) == 99 and c.lastTradeDateOrContractMonth == "20261113":
                out.append(None)
                continue
            c.conId = 100 + i
            c.localSymbol = f"{c.symbol} {getattr(c, 'strike', '')}"
            out.append(c)
        return out

    def reqSecDefOptParams(self, sym, fut, typ, con_id):
        return [SimpleNamespace(exchange="SMART", tradingClass=sym,
                                expirations={"20261106", "20261113", "20261120"},
                                strikes={float(k) for k in range(80, 121)})]  # fmt: skip

    def reqMktData(self, c, ticks, snap, reg):
        self.lines += 1
        self.max_lines = max(self.max_lines, self.lines)
        if c.secType == "STK":
            return Tick(contract=c, last=100.0)
        greeks = SimpleNamespace(impliedVol=0.2, delta=0.5 if c.right == "C" else -0.5,
                                 gamma=0.01, vega=0.1, theta=-0.05, undPrice=100.0)  # fmt: skip
        return Tick(contract=c, bid=1.0, ask=1.1, bidSize=10, askSize=12, last=1.05,
                    volume=5, callOpenInterest=100, putOpenInterest=200, modelGreeks=greeks,
                    marketDataType=1)  # fmt: skip

    def cancelMktData(self, c):
        self.lines -= 1

    def sleep(self, s):
        pass


def test_capture_writes_parquet_manifest_and_releases_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(L, "settings", lambda: {"underlyings": ["SPY"], "weeklies": 2,
                                                "monthlies": 1, "band": 0.02,
                                                "grid_step": 0.01, "dense_band": 0.01})  # fmt: skip
    book = tmp_path / "journal"
    book.mkdir()
    (book / "book.json").write_text(
        json.dumps(
            {
                "positions": [
                    {"underlying": "QQQ", "status": "open"},
                    {"underlying": "IWM", "status": "closed"},
                ]
            }
        )
    )
    ib = FakeIB()
    m = L.capture(date(2026, 11, 5), ib=ib)
    assert set(m["underlyings"]) == {"SPY", "QQQ"}  # journal's open position added
    assert ib.types == [1] and ib.lines == 0 and ib.max_lines <= L.CHUNK
    df = pd.read_parquet(tmp_path / "ibkr" / "options" / "2026-11-05" / "SPY.parquet")
    # expiries 1106, 1113 (weeklies) + 1120 (monthly); strikes 98-102; 99 missing on 1113
    assert sorted(df["expiry"].unique()) == ["20261106", "20261113", "20261120"]
    assert len(df) == 3 * 5 * 2 - 2
    put = df[df["right"] == "P"].iloc[0]
    assert put["open_interest"] == 200 and put["delta"] == -0.5 and put["spot"] == 100.0
    assert m["underlyings"]["SPY"]["quoted"] == len(df)
    again = L.capture(date(2026, 11, 5), ib=FakeIB())  # already captured: skipped, kept
    assert again["underlyings"]["SPY"]["quoted"] == len(df)
    assert sorted(L.check()["underlying"]) == ["QQQ", "SPY"]
