"""Daily entrypoint: data -> sleeves -> portfolio targets -> orders.

uv run python -m horizon_trader.run_daily --dry-run          # print today's targets and orders
uv run python -m horizon_trader.run_daily --mode shadow      # forward test in our own simulator
uv run python -m horizon_trader.run_daily --mode what-if     # IBKR's commission/margin, no orders
uv run python -m horizon_trader.run_daily --mode paper       # market-on-open orders, IBKR paper
uv run python -m horizon_trader.run_daily --mode alpaca      # Alpaca paper, fractional, next open
uv run python -m horizon_trader.run_daily --kill             # kill switch on + cancel all orders

Run after the close (or before the next open): signals use the last complete daily bar and
orders fill at the next open, like the backtest. Shadow and paper keep a virtual
`account.starting_cash` ledger each under data/live/, so the two can be compared fill by fill.
There is no live mode: the IBKR adapter refuses any non-paper account, and the Alpaca one
only takes paper keys (paper-api.alpaca.markets).
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pandas as pd

from horizon_trader.config import DEFAULT_CONFIG, Settings, load_settings
from horizon_trader.execution import Broker, Order, PaperBroker, compute_orders
from horizon_trader.execution.costs import ibkr_costs
from horizon_trader.execution.ledger import Ledger, fill_pending_at_open
from horizon_trader.portfolio import apply_risk_limits, combine_sleeves
from horizon_trader.sleeves import build_sleeve

log = logging.getLogger("horizon_trader")

Mode = Literal["dry-run", "shadow", "what-if", "paper", "alpaca"]
MODES: tuple[Mode, ...] = ("dry-run", "shadow", "what-if", "paper", "alpaca")
BarFetcher = Callable[[list[str]], dict[str, pd.DataFrame]]  # {"open": ..., "close": ...}
NY = "America/New_York"


def plan_orders(
    settings: Settings, prices: pd.DataFrame, broker: Broker
) -> tuple[pd.Series, list[Order], dict[str, float]]:
    asof = prices.index[-1]
    sleeve_weights, allocations = {}, {}
    for name, cfg in settings.sleeves.items():
        sleeve = build_sleeve(name, cfg)
        sleeve_weights[name] = sleeve.target_weights(asof, prices)
        allocations[name] = cfg.allocation

    targets = apply_risk_limits(combine_sleeves(sleeve_weights, allocations), settings.risk)
    last = prices.iloc[-1].dropna().to_dict()
    orders = compute_orders(
        targets, broker.positions(), last, broker.equity(last), settings.execution
    )
    return targets, orders, last


def market_open(now: pd.Timestamp) -> bool:
    """True during the regular session (plus 10 minutes for the closing bar to settle)."""
    now = now.tz_convert(NY)
    minutes = now.hour * 60 + now.minute
    return now.weekday() < 5 and 9 * 60 + 30 <= minutes < 16 * 60 + 10


def _default_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    from horizon_trader.datasources.store import load_bars

    return load_bars(symbols, refresh=True)  # the cache may predate today's close


def run(
    config: Path,
    mode: Mode = "dry-run",
    bars: BarFetcher | None = None,
    *,
    ib=None,
    alpaca=None,
    root: Path | None = None,
    now: pd.Timestamp | None = None,
) -> tuple[pd.Series, list[Order]]:
    """`ib` (an ib_async.IB), `alpaca` (an AlpacaPaper-like api) and `root` (ledger folder)
    exist for tests."""
    if mode not in MODES:
        raise SystemExit(f"unknown mode {mode!r}; there is no live mode")
    settings = load_settings(config)
    now = now if now is not None else pd.Timestamp.now(tz=NY)
    if mode != "dry-run" and market_open(now):
        raise SystemExit("market is open: today's bar is incomplete. Run after 16:10 ET.")

    panels = (bars or _default_bars)(sorted(set(settings.universe)))
    prices = panels["close"].dropna(how="all")
    asof = prices.index[-1].strftime("%Y-%m-%d")
    costs = ibkr_costs(settings.costs.plan, settings.costs.slippage_bps)
    log.info("as of %s, mode %s", asof, mode)

    if mode == "dry-run":
        broker = PaperBroker(cash=settings.account.starting_cash)
        targets, orders, last = plan_orders(settings, prices, broker)
        _log_plan(targets, orders, last)
        log.info("dry run: %d orders not submitted", len(orders))
        return targets, orders

    if mode == "shadow":
        name = f"{settings.live.strategy}_shadow"
        ledger = Ledger.load(name, settings.account.starting_cash, root)
        booked = fill_pending_at_open(ledger, panels["open"], costs)
        log.info("shadow: %d pending orders filled at the open", booked)
        targets, orders = _plan_once(settings, prices, ledger, asof)
        ledger.save()
        return targets, orders

    if mode == "alpaca":
        return _run_alpaca(settings, prices, panels["open"], costs, asof, alpaca, root)
    return _run_ibkr(settings, prices, panels["open"], costs, asof, mode, ib, root)


def _run_alpaca(settings, prices, opens, costs, asof, api, root):
    from horizon_trader.execution import alpaca_book as ab

    if api is None:
        from horizon_trader.execution.alpaca_broker import AlpacaPaper

        api = AlpacaPaper(ab.PREFIX)
    ledger = Ledger.load(settings.live.strategy + ab.SUFFIX, settings.account.starting_cash, root)
    broker = ab.AlpacaBookBroker(api, ledger, settings.live)
    log.info("Alpaca paper account %s, ledger %r", broker.account, ledger.name)
    booked = ab.sync_fills(api, ledger, costs, opens)
    ledger.save()
    log.info("Alpaca: %d new fills booked", booked)
    ab.reconcile(api, ledger)
    targets, orders = _plan_once(settings, prices, ledger, asof, broker)
    ledger.save()
    return targets, orders


def _run_ibkr(settings, prices, opens, costs, asof, mode, ib, root):
    from horizon_trader.execution.ibkr_broker import IBKRBroker, reconcile, sync_fills

    own_connection = ib is None
    if own_connection:
        from horizon_trader.execution.ibkr import connect

        ib = connect(readonly=False)
    try:
        ledger = Ledger.load(settings.live.strategy, settings.account.starting_cash, root)
        broker = IBKRBroker(ib, ledger, settings.live, transmit=mode == "paper")
        log.info("IBKR paper account %s, strategy tag %r", broker.account, ledger.name)
        if mode == "what-if":  # read-only: the ledger is not touched
            targets, orders, last = plan_orders(settings, prices, broker)
            _log_plan(targets, orders, last)
            broker.submit_all(orders, last, asof)
            for w in broker.what_ifs:
                o = w.order
                log.info(
                    "what-if %+g %s: IBKR commission %.2f vs model %.2f, init margin %s %s",
                    o.quantity, o.symbol, w.commission,
                    costs.total(o.quantity, last[o.symbol]), w.margin_change, w.warning,
                )  # fmt: skip
            return targets, orders

        booked = sync_fills(ib, ledger, costs, opens)
        ledger.save()
        log.info("IBKR: %d new fills booked", booked)
        reconcile(ib, broker.account, [ledger])
        targets, orders = _plan_once(settings, prices, ledger, asof, broker)
        ledger.save()
        return targets, orders
    finally:
        if own_connection:
            ib.disconnect()


def _plan_once(settings, prices, ledger: Ledger, asof: str, broker=None):
    """Plan and queue orders unless this signal date was already planned."""
    targets, orders, last = plan_orders(settings, prices, broker or ledger)
    equity = ledger.record_equity(asof, last)
    _log_plan(targets, orders, last)
    log.info(f"{ledger.name}: equity ${equity:,.2f}, cash ${ledger.cash:,.2f}")
    if any(p.asof == asof for p in ledger.pending):
        log.info("orders for %s were already queued; nothing new sent", asof)
        return targets, []
    if broker is not None:
        broker.submit_all(orders, last, asof)  # adds them to ledger.pending once sent
        log.info("sent %d orders for the next open to the broker", len(orders))
    else:
        ledger.add_pending(orders, last, asof)
        log.info("queued %d shadow orders for the next open", len(orders))
    return targets, orders


def _log_plan(targets: pd.Series, orders: list[Order], last: dict[str, float]) -> None:
    log.info("targets:\n%s", targets.round(4).to_string())
    for o in orders:
        log.info("%s %+.4f %s @ ~%.2f", o.order_type, o.quantity, o.symbol, last[o.symbol])


ALPACA_PREFIXES = ("ALPACA_DAILY_BOOK", "ALPACA_COMPETITION_AI", "ALPACA_MOMENTUM",
                   "ALPACA_QQQ_NOISE")  # fmt: skip


def kill_everything() -> None:
    """Kill switch file FIRST (every runner checks it), then cancel open orders at IBKR and at
    every Alpaca paper account with keys in .env. One broker being down doesn't stop the rest."""
    import os

    from horizon_trader.execution.ibkr_broker import kill_switch_path

    path = kill_switch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pd.Timestamp.now(tz=NY).isoformat(), encoding="utf-8")
    log.warning("kill switch ON (%s)", path)
    try:
        from horizon_trader.execution.ibkr import connect
        from horizon_trader.execution.ibkr_broker import kill

        ib = connect(readonly=False)
        try:
            kill(ib)
        finally:
            ib.disconnect()
    except Exception as exc:  # noqa: BLE001
        log.error("IBKR: could not cancel orders (%r)", exc)
    for prefix in ALPACA_PREFIXES:
        if not os.environ.get(f"{prefix}_API_KEY"):
            continue
        try:
            from horizon_trader.execution.alpaca_broker import AlpacaPaper

            AlpacaPaper(prefix).cancel_all()
            log.warning("%s: open Alpaca orders cancelled", prefix)
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            log.error("%s: could not cancel orders (%r)", prefix, exc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", choices=MODES, default="dry-run")
    parser.add_argument("--dry-run", action="store_true", help="same as --mode dry-run")
    parser.add_argument("--kill", action="store_true",
                        help="kill switch on, cancel open orders at IBKR and every Alpaca account")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.kill:
        kill_everything()
        return
    from horizon_trader.execution.ibkr_broker import GuardError

    try:
        run(args.config, "dry-run" if args.dry_run else args.mode)
    except GuardError as e:
        raise SystemExit(f"STOPPED: {e}") from None


if __name__ == "__main__":
    main()
