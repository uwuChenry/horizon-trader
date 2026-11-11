"""IBKR live option quotes with a fake IB, and the Alpaca follower's source rule."""

import math

import pytest

from horizon_trader.datasources.ibkr_quotes import IBKRQuotes, parse_occ
from horizon_trader.execution.alpaca_broker import AlpacaPaper


class Ticker:
    def __init__(self, contract, bid, ask):
        self.contract, self.bid, self.ask = contract, bid, ask


class FakeIB:
    """Quotes by OCC-ish key; `unknown` contracts don't qualify; -1 = no quote (IB's convention)."""

    def __init__(self, book, unknown=()):
        self.book, self.unknown, self.requested, self.cancelled = book, set(unknown), [], 0
        self.types = []

    def reqMarketDataType(self, t):
        self.types.append(t)

    def qualifyContracts(self, *cs):
        for i, c in enumerate(cs):
            key = (c.symbol, c.lastTradeDateOrContractMonth, c.right, c.strike)
            if key not in self.unknown:
                c.conId = 1000 + i

    def reqMktData(self, c, *a):
        self.requested.append(c)
        bid, ask = self.book.get((c.symbol, c.lastTradeDateOrContractMonth, c.right, c.strike),
                                 (-1.0, -1.0))  # fmt: skip
        return Ticker(c, bid, ask)

    def sleep(self, s):
        pass

    def cancelMktData(self, c):
        self.cancelled += 1


A, B, C = "SPY261218C00770000", "SPY261218P00700500", "QQQ261120C00650000"


def test_parse_occ():
    assert parse_occ(A) == ("SPY", "20261218", "C", 770.0)
    assert parse_occ(B) == ("SPY", "20261218", "P", 700.5)
    with pytest.raises(ValueError):
        parse_occ("SPY")


def test_live_quotes_skip_missing_and_unqualified_contracts():
    ib = FakeIB({("SPY", "20261218", "C", 770.0): (14.9, 15.1),
                 ("SPY", "20261218", "P", 700.5): (-1.0, -1.0)},  # no quote yet
                unknown={("QQQ", "20261120", "C", 650.0)})  # fmt: skip
    q = IBKRQuotes(ib=ib, timeout=0.01)
    assert q.quotes([A, B, C]) == {A: (14.9, 15.1)}
    assert ib.types == [1] and ib.cancelled == 2  # live data only; every line released
    assert ib.requested[0].tradingClass == "SPY" and ib.requested[0].exchange == "SMART"
    ib.book[("SPY", "20261218", "C", 770.0)] = (1.0, 1.1)
    assert q.quotes([A]) == {A: (14.9, 15.1)}  # served from the 30 s cache


def test_failed_connection_means_fallback(monkeypatch):
    import horizon_trader.execution.ibkr as ibkr

    def refuse(**kw):
        raise ConnectionRefusedError("gateway down")

    monkeypatch.setattr(ibkr, "connect", refuse)
    q = IBKRQuotes()
    assert q.quotes([A]) == {} and q._failed
    assert q.quotes([A]) == {}  # doesn't retry the connection on every call


def test_alpaca_uses_ibkr_only_when_it_has_every_leg():
    class Live:
        def __init__(self, have):
            self.have = have

        def quotes(self, symbols):
            return {s: (2.0, 2.1) for s in symbols if s in self.have}

    broker = AlpacaPaper.__new__(AlpacaPaper)
    broker.live_quotes = Live({A, B})
    broker.last_quote_source = ""
    assert broker.option_quotes([A, B]) == {A: (2.0, 2.1), B: (2.0, 2.1)}
    assert broker.last_quote_source == "ibkr"

    class Indicative:  # stands in for Alpaca's data client
        def get_option_latest_quote(self, req):
            class Q:
                bid_price, ask_price = 1.0, 1.2

            return {s: Q() for s in req.symbol_or_symbols}

    broker.options = Indicative()
    got = broker.option_quotes([A, C])  # IBKR lacks C -> both legs from Alpaca
    assert broker.last_quote_source == "alpaca-indicative" and got[A] == (1.0, 1.2)
    assert not math.isnan(got[C][0])


def test_stock_tickers_get_live_nbbo():
    ib = FakeIB({("NVDA", "", "", 0.0): (199.98, 200.02), A_KEY: (14.9, 15.1)})
    q = IBKRQuotes(ib=ib, timeout=0.01)
    assert q.quotes(["NVDA", A]) == {"NVDA": (199.98, 200.02), A: (14.9, 15.1)}
    stock = next(c for c in ib.requested if c.symbol == "NVDA")
    assert stock.secType == "STK" and stock.exchange == "SMART" and stock.currency == "USD"


A_KEY = ("SPY", "20261218", "C", 770.0)


def test_alpaca_stock_quote_prefers_ibkr_then_iex():
    class Live:
        def __init__(self, have):
            self.have = have

        def quotes(self, symbols):
            return {s: (99.99, 100.01) for s in symbols if s in self.have}

    class IEX:  # stands in for Alpaca's stock data client
        def get_stock_latest_quote(self, req):
            class Q:
                bid_price, ask_price = 99.5, 100.5

            return {req.symbol_or_symbols: Q()}

    broker = AlpacaPaper.__new__(AlpacaPaper)
    broker.stocks, broker.live_quotes = IEX(), Live({"NVDA"})
    assert broker.stock_quote("NVDA") == (99.99, 100.01) and broker.last_stock_source == "ibkr"
    assert broker.stock_quote("AMD") == (99.5, 100.5)
    assert broker.last_stock_source == "alpaca-iex"
    broker.live_quotes = None
    assert broker.stock_quote("NVDA") == (99.5, 100.5)
