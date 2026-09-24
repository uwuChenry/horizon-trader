"""Daily entrypoint, run after the close: data -> sleeves -> portfolio targets -> orders.

uv run python -m horizon_trader.run_daily --dry-run
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from horizon_trader.config import DEFAULT_CONFIG, Settings, load_settings
from horizon_trader.execution import Broker, Order, PaperBroker, compute_orders
from horizon_trader.portfolio import apply_risk_limits, combine_sleeves
from horizon_trader.sleeves import build_sleeve

log = logging.getLogger("horizon_trader")

PriceFetcher = Callable[[list[str]], pd.DataFrame]


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


def run(
    config: Path, dry_run: bool, fetch: PriceFetcher | None = None
) -> tuple[pd.Series, list[Order]]:
    if not dry_run:
        raise SystemExit("Live execution not wired up yet (IBKR adapter is phase 4); use --dry-run")
    settings = load_settings(config)
    if fetch is None:
        from horizon_trader.data.yf_source import fetch_closes as fetch

    prices = fetch(sorted(set(settings.universe)))
    broker = PaperBroker(cash=settings.account.starting_cash)

    targets, orders, last = plan_orders(settings, prices, broker)
    log.info("as of %s", prices.index[-1].date())
    log.info("targets:\n%s", targets.round(4).to_string())
    for o in orders:
        log.info("%s %+.4f %s @ ~%.2f", o.order_type, o.quantity, o.symbol, last[o.symbol])
    log.info("dry run: %d orders not submitted", len(orders))
    return targets, orders


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true", help="print orders, submit nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.config, args.dry_run)


if __name__ == "__main__":
    main()
