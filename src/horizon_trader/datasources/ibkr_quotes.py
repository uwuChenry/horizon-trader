"""Live quotes (bid/ask) from IBKR, read-only, for a handful of options or stocks at a time.

Used by the forecast journal (agents/market.py: the legs it prices, the positions it marks and
the packet's implied moves) and by the AI contest trader (option limits, stock quotes and the
underlying prices its stops watch). Callers fall back to their delayed/indicative source for any
symbol this returns nothing for: Gateway down, not logged in, market closed, or no quote yet.

    IBKRQuotes().quotes(["SPY261218C00770000", "NVDA"]) -> {symbol: (bid, ask)}

Option symbols are OCC-style as Yahoo writes them: ROOT + YYMMDD + C/P + strike x 1000
(8 digits). Anything else is a US stock/ETF ticker, quoted on SMART: the consolidated NBBO from
the account's real-time US equity subscription (unlike Alpaca's free feed, which is IEX only).
The connection is `readonly=True` (it can't place orders) with its own client id, opened on the
first request and closed at exit. Needs the account's OPRA subscription shared with the paper
login; requests are chunked to stay under IBKR's 100 simultaneous market-data lines.
"""

from __future__ import annotations

import atexit
import logging
import math
import time

log = logging.getLogger(__name__)

CHUNK = 40  # contracts per batch (IBKR allows ~100 market-data lines at once)


def parse_occ(symbol: str) -> tuple[str, str, str, float]:
    """'SPY261218C00770000' -> ('SPY', '20261218', 'C', 770.0)."""
    s = symbol.strip()
    if len(s) < 16:
        raise ValueError(f"not an OCC option symbol: {symbol!r}")
    root, yymmdd, right, strike = s[:-15], s[-15:-9], s[-9], s[-8:]
    if not root or right not in "CP" or not (yymmdd + strike).isdigit():
        raise ValueError(f"not an OCC option symbol: {symbol!r}")
    return root, "20" + yymmdd, right, int(strike) / 1000


def _ok(x) -> bool:
    return x is not None and not math.isnan(x) and x >= 0


class IBKRQuotes:
    def __init__(self, client_id: int = 31, timeout: float = 4.0, ttl: float = 30.0, ib=None):
        self.client_id, self.timeout, self.ttl = client_id, timeout, ttl
        self._ib = ib  # tests pass a fake
        self._failed = False
        self._cache: dict[str, tuple[float, tuple[float, float]]] = {}

    def _conn(self):
        if self._ib is None and not self._failed:
            try:
                from horizon_trader.execution.ibkr import connect

                self._ib = connect(readonly=True, client_id=self.client_id)
                atexit.register(self.close)
            except Exception as exc:  # noqa: BLE001 - any failure means "use the fallback"
                log.warning("IBKR option quotes unavailable (%r); using the fallback source", exc)
                self._failed = True
        return self._ib

    def close(self) -> None:
        if self._ib is not None:
            try:
                self._ib.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._ib = None

    def quotes(self, symbols: list[str]) -> dict[str, tuple[float, float]]:
        now = time.monotonic()
        out = {}
        for s in symbols:
            hit = self._cache.get(s)
            if hit and now - hit[0] < self.ttl:
                out[s] = hit[1]
        todo = [s for s in dict.fromkeys(symbols) if s not in out]
        if not todo or (ib := self._conn()) is None:
            return out
        for i in range(0, len(todo), CHUNK):
            try:
                got = self._batch(ib, todo[i : i + CHUNK])
            except Exception as exc:  # noqa: BLE001
                log.warning("IBKR quote batch failed (%r); using the fallback for it", exc)
                continue
            for s, q in got.items():
                self._cache[s] = (time.monotonic(), q)
            out |= got
        return out

    def _batch(self, ib, symbols: list[str]) -> dict[str, tuple[float, float]]:
        from ib_async import Option, Stock

        contracts = {}
        for s in symbols:
            try:
                root, expiry, right, strike = parse_occ(s)
            except ValueError:
                if s.isalpha() or s.replace(".", "").isalpha():  # a stock/ETF ticker
                    contracts[s] = Stock(s.replace(".", " "), "SMART", "USD")
                continue
            contracts[s] = Option(root, expiry, strike, right, "SMART", currency="USD",
                                  multiplier="100", tradingClass=root)  # fmt: skip
        ib.reqMarketDataType(1)  # live only: a delayed IBKR quote is no better than the fallback
        ib.qualifyContracts(*contracts.values())
        tickers = {s: ib.reqMktData(c, "", False, False) for s, c in contracts.items() if c.conId}
        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                ib.sleep(0.25)
                if all(_ok(t.bid) and _ok(t.ask) and t.ask > 0 for t in tickers.values()):
                    break
        finally:
            for t in tickers.values():
                ib.cancelMktData(t.contract)
        return {
            s: (float(t.bid), float(t.ask))
            for s, t in tickers.items()
            if _ok(t.bid) and _ok(t.ask) and t.ask > 0 and t.ask >= t.bid
        }
