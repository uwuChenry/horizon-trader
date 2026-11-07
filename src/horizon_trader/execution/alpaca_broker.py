"""Alpaca PAPER adapter: a thin wrapper over alpaca-py that the competition follower
(`agents/competition.py`) talks to, so tests can swap in a fake.

PAPER ONLY: keys must be paper keys (PK...) and the client is built with `paper=True`
(paper-api.alpaca.markets). There is deliberately no live switch.

Order conventions:
- Every order is `day` time-in-force with our own `client_order_id`, so a crashed run can find
  what it already sent instead of sending it twice.
- Option legs carry an explicit position intent (buy_to_open, sell_to_close, ...).
- A debit spread opens as ONE multi-leg (mleg) limit order with a positive net debit (Alpaca's
  documented case). Spreads are closed leg by leg with market orders, short leg first, which
  avoids mleg credit pricing (its sign convention isn't documented) and never leaves the short
  leg uncovered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from horizon_trader.execution.alpaca_check import paper_keys

NY = ZoneInfo("America/New_York")
# no more fills will come for these (day orders end as expired/done_for_day)
FINAL = {"filled", "canceled", "expired", "rejected", "done_for_day", "replaced", "stopped",
         "suspended"}  # fmt: skip


@dataclass(frozen=True)
class Leg:
    symbol: str
    side: str  # "buy" | "sell"
    intent: str = ""  # buy_to_open | sell_to_open | buy_to_close | sell_to_close; "" for stock


@dataclass(frozen=True)
class OrderSpec:
    client_id: str
    legs: tuple[Leg, ...]
    qty: float
    limit: float | None  # None = market order (single leg only)
    tif: str = "day"  # "day", or "cls" = market-on-close (Alpaca: submit by 15:50 ET)
    stop: float | None = None


@dataclass
class LegFill:
    symbol: str
    side: str
    filled_qty: float
    avg_price: float | None


@dataclass
class OrderInfo:
    client_id: str
    status: str
    filled_qty: float
    avg_price: float | None
    filled_at: str | None  # New York wall clock, "YYYY-MM-DD HH:MM:SS"
    legs: list[LegFill] = field(default_factory=list)

    @property
    def final(self) -> bool:
        return self.status in FINAL


def _f(x) -> float | None:
    return None if x is None or x == "" else float(x)


def _info(o) -> OrderInfo:
    when = o.filled_at.astimezone(NY).strftime("%Y-%m-%d %H:%M:%S") if o.filled_at else None
    legs = [
        LegFill(lg.symbol, getattr(lg.side, "value", str(lg.side)), _f(lg.filled_qty) or 0.0,
                _f(lg.filled_avg_price))
        for lg in (o.legs or [])
    ]  # fmt: skip
    if not legs:
        legs = [LegFill(o.symbol, getattr(o.side, "value", str(o.side)), _f(o.filled_qty) or 0.0,
                        _f(o.filled_avg_price))]  # fmt: skip
    return OrderInfo(
        client_id=o.client_order_id, status=getattr(o.status, "value", str(o.status)),
        filled_qty=_f(o.filled_qty) or 0.0, avg_price=_f(o.filled_avg_price), filled_at=when,
        legs=legs,
    )  # fmt: skip


def order_request(spec: OrderSpec):
    """The alpaca-py request for `spec` (separate so tests can check it offline)."""
    from alpaca.trading.enums import OrderClass, OrderSide, PositionIntent, TimeInForce
    from alpaca.trading.requests import (
        LimitOrderRequest,
        MarketOrderRequest,
        OptionLegRequest,
        StopLimitOrderRequest,
        StopOrderRequest,
    )

    common = {"qty": spec.qty, "time_in_force": TimeInForce(spec.tif),
              "client_order_id": spec.client_id}  # fmt: skip
    if len(spec.legs) > 1:
        if spec.stop is not None:
            raise ValueError("multi-leg orders cannot have a stop")
        if spec.limit is None:
            raise ValueError("multi-leg orders are limit orders here")
        legs = [
            OptionLegRequest(symbol=lg.symbol, ratio_qty=1, side=OrderSide(lg.side),
                             position_intent=PositionIntent(lg.intent))
            for lg in spec.legs
        ]  # fmt: skip
        return LimitOrderRequest(
            order_class=OrderClass.MLEG, legs=legs, limit_price=spec.limit, **common
        )
    leg = spec.legs[0]
    kw = {"symbol": leg.symbol, "side": OrderSide(leg.side), **common}
    if leg.intent:
        kw["position_intent"] = PositionIntent(leg.intent)
    if spec.stop is not None:
        if spec.limit is not None:
            return StopLimitOrderRequest(stop_price=spec.stop, limit_price=spec.limit, **kw)
        return StopOrderRequest(stop_price=spec.stop, **kw)
    if spec.limit is None:
        return MarketOrderRequest(**kw)
    return LimitOrderRequest(limit_price=spec.limit, **kw)


class AlpacaPaper:
    """`live_quotes` (e.g. `datasources.ibkr_quotes.IBKRQuotes`) is asked first for option
    quotes; Alpaca's free indicative feed is the fallback. `last_quote_source` says which."""

    def __init__(self, prefix: str = "ALPACA_COMPETITION_AI", live_quotes=None):
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.trading.client import TradingClient

        key, secret = paper_keys(prefix=prefix)
        self.trading = TradingClient(key, secret, paper=True)
        self.options = OptionHistoricalDataClient(key, secret)
        self.stocks = StockHistoricalDataClient(key, secret)
        self.live_quotes = live_quotes
        self.last_quote_source = ""

    def account(self) -> dict:
        a = self.trading.get_account()
        return {
            "account": a.account_number, "status": getattr(a.status, "value", str(a.status)),
            "equity": float(a.equity), "cash": float(a.cash),
            "options_level": int(a.options_trading_level or 0),
        }  # fmt: skip

    def is_open(self) -> bool:
        return bool(self.trading.get_clock().is_open)

    def positions(self) -> dict[str, float]:
        out = {}
        for p in self.trading.get_all_positions():
            q = float(p.qty)
            if "short" in str(p.side).lower() and q > 0:
                q = -q
            out[p.symbol] = q
        return out

    def option_quotes(self, symbols: list[str]) -> dict[str, tuple[float, float]]:
        """(bid, ask): live IBKR if it has every symbol (a spread's legs must come from one
        source), else Alpaca's free 'indicative' feed (approximate; OPRA needs a paid plan)."""
        if self.live_quotes is not None:
            got = self.live_quotes.quotes(symbols)
            if symbols and all(s in got for s in symbols):
                self.last_quote_source = "ibkr"
                return {s: got[s] for s in symbols}
        self.last_quote_source = "alpaca-indicative"
        from alpaca.data.enums import OptionsFeed
        from alpaca.data.requests import OptionLatestQuoteRequest

        q = self.options.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=symbols, feed=OptionsFeed.INDICATIVE)
        )
        return {s: (float(v.bid_price or 0), float(v.ask_price or 0)) for s, v in q.items()}

    def stock_quote(self, symbol: str) -> tuple[float, float]:
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockLatestQuoteRequest

        v = self.stocks.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
        )[symbol]
        return float(v.bid_price or 0), float(v.ask_price or 0)

    def session(self, day: str) -> tuple[str, str] | None:
        """(open, close) New York wall clock "HH:MM" of `day`'s regular session, None if the
        market is closed that day (Alpaca's calendar knows holidays and 13:00 half days)."""
        from alpaca.trading.requests import GetCalendarRequest

        cal = self.trading.get_calendar(GetCalendarRequest(start=day, end=day))
        if not cal or str(cal[0].date) != day:
            return None
        return cal[0].open.strftime("%H:%M"), cal[0].close.strftime("%H:%M")

    def asset(self, symbol: str) -> dict:
        a = self.trading.get_asset(symbol)
        flags = ("tradable", "fractionable", "shortable", "easy_to_borrow")
        return {f: bool(getattr(a, f)) for f in flags}

    def minute_bars(self, symbol: str, start, end=None) -> list[dict]:
        """Free IEX-feed 1-minute bars (one exchange's trades: a proxy for the consolidated
        tape). Each: ts (bar start, NY), open, high, low, close, volume."""
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute,
                               start=start, end=end, feed=DataFeed.IEX)  # fmt: skip
        bars = self.stocks.get_stock_bars(req).data.get(symbol, [])
        return [
            {"ts": b.timestamp.astimezone(NY), "open": float(b.open), "high": float(b.high),
             "low": float(b.low), "close": float(b.close), "volume": float(b.volume)}
            for b in bars
        ]  # fmt: skip

    def order(self, client_id: str) -> OrderInfo | None:
        from alpaca.common.exceptions import APIError

        try:
            return _info(self.trading.get_order_by_client_id(client_id))
        except APIError as e:
            if getattr(e, "status_code", None) == 404 or "not found" in str(e).lower():
                return None
            raise

    def submit(self, spec: OrderSpec) -> OrderInfo:
        return _info(self.trading.submit_order(order_request(spec)))

    def cancel(self, client_id: str) -> None:
        from alpaca.common.exceptions import APIError

        try:
            order = self.trading.get_order_by_client_id(client_id)
        except APIError as e:
            if getattr(e, "status_code", None) == 404 or "not found" in str(e).lower():
                return
            raise
        if getattr(order.status, "value", str(order.status)) not in FINAL:
            self.trading.cancel_order_by_id(order.id)

    def cancel_all(self) -> None:
        self.trading.cancel_orders()
