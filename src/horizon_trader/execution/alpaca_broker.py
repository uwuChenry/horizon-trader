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
    from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest, OptionLegRequest

    common = {"qty": spec.qty, "time_in_force": TimeInForce.DAY, "client_order_id": spec.client_id}
    if len(spec.legs) > 1:
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
    if spec.limit is None:
        return MarketOrderRequest(**kw)
    return LimitOrderRequest(limit_price=spec.limit, **kw)


class AlpacaPaper:
    def __init__(self, prefix: str = "ALPACA_COMPETITION_AI"):
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.trading.client import TradingClient

        key, secret = paper_keys(prefix=prefix)
        self.trading = TradingClient(key, secret, paper=True)
        self.options = OptionHistoricalDataClient(key, secret)
        self.stocks = StockHistoricalDataClient(key, secret)

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
        """(bid, ask) from the free 'indicative' feed (approximate; OPRA needs a paid plan)."""
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

    def cancel_all(self) -> None:
        self.trading.cancel_orders()
