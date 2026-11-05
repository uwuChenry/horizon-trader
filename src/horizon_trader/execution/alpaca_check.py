"""Alpaca PAPER account check. Read-only: it never submits, replaces or cancels orders.

    uv run python -m horizon_trader.execution.alpaca_check

Reads ALPACA_API_KEY / ALPACA_SECRET_KEY from .env. Prints the account, positions,
open orders, a SPY stock quote (free IEX feed) and an at-the-money SPY call from the
free 'indicative' options feed, then tries the real OPRA feed (needs Algo Trader Plus).
Paper keys start with 'PK'; a live key ('AK') is refused.
"""

from __future__ import annotations

import os
from datetime import date

import horizon_trader.config  # noqa: F401  (loads .env)


def paper_keys(env: dict[str, str] | None = None, prefix: str = "ALPACA") -> tuple[str, str]:
    """(key, secret) from <prefix>_API_KEY / <prefix>_SECRET_KEY; refuses missing or live keys.

    Each Alpaca paper account has its own key pair, so each gets its own prefix (e.g.
    ALPACA_COMPETITION_AI for the AI competition account)."""
    env = os.environ if env is None else env
    k, s = f"{prefix}_API_KEY", f"{prefix}_SECRET_KEY"
    key, secret = env.get(k, "").strip(), env.get(s, "").strip()
    if not key or not secret:
        raise SystemExit(
            f"{k} / {s} are not set in .env.\n"
            "Alpaca dashboard -> switch to that Paper account -> API Keys -> Generate."
        )
    if not key.startswith("PK"):
        raise SystemExit(
            f"{k} starts with {key[:2]!r}, not 'PK': that is not a paper key. "
            "This repo only connects to Alpaca paper."
        )
    return key, secret


def main() -> None:
    from alpaca.common.exceptions import APIError
    from alpaca.data.enums import DataFeed, OptionsFeed
    from alpaca.data.historical.option import OptionHistoricalDataClient
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from alpaca.data.requests import OptionChainRequest, StockLatestQuoteRequest
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    key, secret = paper_keys()
    trading = TradingClient(key, secret, paper=True)

    a = trading.get_account()
    print(f"account {a.account_number}  status {a.status}")
    for name in ("equity", "cash", "buying_power", "options_buying_power"):
        v = getattr(a, name, None)
        print(f"  {name:<20} {float(v):>12,.2f}" if v is not None else f"  {name:<20} n/a")
    print(
        f"  multiplier {a.multiplier}  shorting {a.shorting_enabled}  "
        f"PDT flag {a.pattern_day_trader}  day trades {a.daytrade_count}"
    )
    print(
        f"  options level approved {a.options_approved_level} / trading {a.options_trading_level}"
    )

    positions = trading.get_all_positions()
    print(f"positions: {len(positions)}")
    for p in positions:
        print(f"  {p.symbol:<22} {float(p.qty):>10} @ {float(p.avg_entry_price):,.2f}")
    orders = trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
    print(f"open orders: {len(orders)}")

    stocks = StockHistoricalDataClient(key, secret)
    q = stocks.get_stock_latest_quote(
        StockLatestQuoteRequest(symbol_or_symbols="SPY", feed=DataFeed.IEX)
    )["SPY"]
    mid = (q.bid_price + q.ask_price) / 2 if q.bid_price and q.ask_price else q.ask_price
    print(f"\nSPY (IEX feed): bid {q.bid_price} ask {q.ask_price} at {q.timestamp}")

    options = OptionHistoricalDataClient(key, secret)
    for feed in (OptionsFeed.INDICATIVE, OptionsFeed.OPRA):
        try:
            chain = options.get_option_chain(
                OptionChainRequest(
                    underlying_symbol="SPY",
                    feed=feed,
                    type="call",
                    expiration_date_gte=date.today(),
                    strike_price_gte=mid - 2,
                    strike_price_lte=mid + 2,
                )
            )
        except APIError as e:
            print(f"options feed {feed.value}: NOT available -> {e}")
            continue
        if not chain:
            print(f"options feed {feed.value}: no contracts returned")
            continue
        sym = min(chain)  # OCC symbols sort by expiry, then strike
        snap = chain[sym]
        oq = snap.latest_quote
        print(
            f"options feed {feed.value}: {sym} bid {oq.bid_price if oq else None} "
            f"ask {oq.ask_price if oq else None} iv {snap.implied_volatility} "
            f"at {oq.timestamp if oq else None}"
        )


if __name__ == "__main__":
    main()
