"""IBKR connection via ib_async. For now: a read-only connection check.

    uv run python -m horizon_trader.execution.ibkr

Reads IB_HOST / IB_PORT / IB_CLIENT_ID from .env. Connects with readonly=True, so it
cannot place orders. The order-placing Broker adapter comes next (phase 4).
"""

from __future__ import annotations

import os

from ib_async import IB

import horizon_trader.config  # noqa: F401  (loads .env)

SUMMARY_TAGS = ("NetLiquidation", "TotalCashValue", "BuyingPower", "AvailableFunds")


REQUEST_TIMEOUT = 60.0  # seconds; ib_async's default (0) waits forever on a stuck Gateway


def connect(readonly: bool = True, client_id: int | None = None) -> IB:
    """`client_id` overrides IB_CLIENT_ID so tools can run next to the daily run.

    Every blocking request gets REQUEST_TIMEOUT: on 2026-11-10 the Gateway stopped answering
    at ~15:43 and requests without a timeout (options capture, orb sync) hung until it
    restarted at 23:42. Callers may lower it."""
    ib = IB()
    ib.connect(
        host=os.environ.get("IB_HOST", "127.0.0.1"),
        port=int(os.environ.get("IB_PORT", "4002")),
        clientId=client_id or int(os.environ.get("IB_CLIENT_ID", "1")),
        readonly=readonly,
        timeout=10,
    )
    ib.RequestTimeout = REQUEST_TIMEOUT
    return ib


def main() -> None:
    port = os.environ.get("IB_PORT", "4002")
    try:
        ib = connect(readonly=True)
    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        raise SystemExit(
            f"Could not connect on port {port}: {e!r}\n"
            "Is IB Gateway/TWS running and logged in to the PAPER account, with the API "
            "enabled and the port matching IB_PORT (Gateway paper 4002, TWS paper 7497)?"
        ) from None

    try:
        accounts = ib.managedAccounts()
        print(f"connected: accounts {accounts}")
        if not all(a.startswith("D") for a in accounts):
            print("WARNING: paper account IDs usually start with 'D'. This may be a LIVE account.")
        for v in ib.accountSummary():
            if v.tag in SUMMARY_TAGS:
                print(f"  {v.tag:<16} {float(v.value):>12,.2f} {v.currency}")
        positions = ib.positions()
        print(f"positions: {len(positions)}")
        for p in positions:
            print(f"  {p.contract.symbol:<6} {p.position:>10} @ {p.avgCost:,.2f}")
    finally:
        ib.disconnect()


if __name__ == "__main__":
    main()
