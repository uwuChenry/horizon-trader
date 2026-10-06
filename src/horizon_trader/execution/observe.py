"""Read-only paper execution evidence, written as append-only timestamped JSONL.

python -m horizon_trader.execution.observe --seconds 20
python -m horizon_trader.execution.observe --session  # 09:24–16:05 New York
No order submission, cancellation, account reset, or ledger mutation occurs here.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from horizon_trader.config import data_dir

NY = "America/New_York"


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class EvidenceLog:
    def __init__(self, root: Path | None = None):
        self.root = root or data_dir() / "live" / "observations"
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_id = uuid.uuid4().hex

    def write(self, kind, **fields):
        now = pd.Timestamp.now(tz="UTC")
        path = self.root / f"{now.tz_convert(NY):%Y-%m-%d}.jsonl"
        row = clean(dict(observed_utc=now, run_id=self.run_id, kind=kind, **fields))
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, allow_nan=False) + "\n")


def order_record(trade):
    order, status = trade.order, trade.orderStatus
    return dict(
        symbol=trade.contract.symbol,
        order_id=order.orderId,
        permanent_id=order.permId,
        strategy=order.orderRef,
        action=order.action,
        quantity=order.totalQuantity,
        order_type=order.orderType,
        limit=order.lmtPrice,
        stop=order.auxPrice,
        status=status.status,
        filled=status.filled,
        remaining=status.remaining,
        average_fill=status.avgFillPrice,
    )


def fill_record(fill):
    ex = fill.execution
    return dict(
        symbol=fill.contract.symbol,
        execution_id=ex.execId,
        order_id=ex.orderId,
        permanent_id=ex.permId,
        strategy=ex.orderRef,
        source_time=ex.time,
        side=ex.side,
        shares=ex.shares,
        price=ex.price,
        exchange=ex.exchange,
    )


def candidate_decisions(ib, contracts, symbols, log):
    """Observe ORB decisions at four virtual sizes; never submits an order."""
    from horizon_trader.intraday import features, orb_live

    now = pd.Timestamp.now(tz=NY)
    history = orb_live.history(now.date())
    history_end = pd.Timestamp(history.attrs["history_ends"])
    # Business-day check fails closed around holidays; logs permit later audit.
    expected = now.tz_localize(None).normalize() - pd.offsets.BDay(1)
    if history_end != expected:
        log.write(
            "decision_unavailable",
            reason="stale_or_holiday_history",
            history_end=history_end,
            expected_previous_weekday=expected,
        )
        return
    chosen = [contracts[s] for s in symbols if s in contracts]
    bars = orb_live.fetch_or_bars(ib, chosen)
    if bars.empty:
        log.write("decision_unavailable", reason="missing_opening_bars")
        return
    ranges = features.opening_range(bars, now.date(), 5)
    candidates = orb_live.pick(history, ranges)
    log.write(
        "candidates",
        history_end=history_end,
        rows=candidates.reset_index().head(10).to_dict("records"),
    )
    for capital in (5000, 10000, 15000, 20000):
        for allocation, weight in (("frozen", 0.20332137002741696), ("reduced", 0.25)):
            plan = (
                None
                if candidates.empty
                else orb_live.plan_trade(candidates.iloc[0], capital * weight)
            )
            log.write(
                "decision",
                strategy="orb",
                allocation=allocation,
                starting_capital=capital,
                plan=asdict(plan) if plan else None,
                submitted=False,
                note="Unfunded intent only; shared buying power not approved; no order sent",
            )


def capture(seconds=20.0, session=False):
    from ib_async import ExecutionFilter, Stock

    from horizon_trader.execution.ibkr import connect
    from horizon_trader.intraday.scanner_log import run_scan

    log = EvidenceLog()
    log.write("start", readonly=True, requested_seconds=seconds, session=session)
    try:
        ib = connect(readonly=True, client_id=31)
    except Exception as exc:
        log.write("connection_failed", error=type(exc).__name__, detail=str(exc))
        raise
    contracts = {}
    try:
        accounts = ib.managedAccounts()
        if not accounts or any(not a.startswith("DU") for a in accounts):
            raise RuntimeError("Observer requires only DU paper accounts")
        log.write("connected", paper_accounts=len(accounts), note="Account identifiers omitted")
        ib.RequestTimeout = 20

        def status(trade):
            log.write("order_status", **order_record(trade))

        def execution(trade, fill):
            log.write("execution", **fill_record(fill))

        def commission(trade, fill, report):
            log.write(
                "commission",
                execution_id=report.execId,
                commission=report.commission,
                currency=report.currency,
                realized_pnl=report.realizedPNL,
            )

        def error(req_id, code, message, contract=None):
            log.write(
                "api_error",
                request_id=req_id,
                code=code,
                message=message,
                symbol=getattr(contract, "symbol", None),
            )

        def quotes(tickers):
            for ticker in tickers:
                valid = (
                    math.isfinite(ticker.bid)
                    and math.isfinite(ticker.ask)
                    and ticker.bid > 0
                    and ticker.ask >= ticker.bid
                )
                log.write(
                    "quote",
                    symbol=ticker.contract.symbol,
                    api_update_time=ticker.time,
                    exchange_quote_time=None,
                    bid=ticker.bid,
                    ask=ticker.ask,
                    bid_size=ticker.bidSize,
                    ask_size=ticker.askSize,
                    last=ticker.last,
                    market_data_type=ticker.marketDataType,
                    valid_two_sided=valid,
                    last_trade_time=getattr(ticker, "rtTime", None),
                )

        ib.orderStatusEvent += status
        ib.openOrderEvent += status
        ib.execDetailsEvent += execution
        ib.commissionReportEvent += commission
        ib.errorEvent += error
        ib.pendingTickersEvent += quotes
        for value in ib.accountSummary():
            if value.tag in {
                "NetLiquidation",
                "TotalCashValue",
                "BuyingPower",
                "AvailableFunds",
                "InitMarginReq",
                "MaintMarginReq",
                "DayTradesRemaining",
                "AccountType",
            }:
                log.write("account", tag=value.tag, value=value.value, currency=value.currency)
        for position in ib.positions():
            log.write(
                "position",
                symbol=position.contract.symbol,
                quantity=position.position,
                average_cost=position.avgCost,
            )
        for trade in ib.reqAllOpenOrders():
            log.write("open_order_snapshot", **order_record(trade))
        for account in accounts:
            for fill in ib.reqExecutions(ExecutionFilter(acctCode=account)):
                log.write("execution_snapshot", **fill_record(fill))
                report = fill.commissionReport
                log.write(
                    "commission_snapshot",
                    execution_id=report.execId,
                    commission=report.commission,
                    currency=report.currency,
                )

        def subscribe(symbols):
            fresh = [s for s in symbols if s not in contracts][: max(0, 60 - len(contracts))]
            if fresh:
                for contract in ib.qualifyContracts(*[Stock(s, "SMART", "USD") for s in fresh]):
                    contracts[contract.symbol] = contract
                    ib.reqMktData(contract, "", False, False)
                log.write("subscriptions", symbols=list(contracts))

        subscribe(["SPY", "QQQ", "IWM", "EFA", "EEM", "VNQ", "DBC", "TLT", "IEF", "GLD"])
        started = time.monotonic()
        scanned = set()
        last_heartbeat = 0.0
        last_snapshot = time.monotonic()
        while True:
            now = pd.Timestamp.now(tz=NY)
            if session:
                if now.weekday() >= 5 or now.strftime("%H:%M") >= "16:05":
                    break
                for clock in ("09:25", "09:35"):
                    if clock <= now.strftime("%H:%M") < "09:37" and clock not in scanned:
                        scanned.add(clock)
                        try:
                            symbols = run_scan(ib, "SCAN_stVolumeVsAvg5min_DESC", "CORP")
                            log.write("scanner", scheduled=clock, symbols=symbols)
                            subscribe(symbols)
                            if clock == "09:35":
                                candidate_decisions(ib, contracts, symbols, log)
                        except Exception as exc:
                            log.write("scanner_failed", scheduled=clock, error=str(exc))
            elif time.monotonic() - started >= seconds:
                break
            if not ib.isConnected():
                raise ConnectionError("IBKR disconnected; collector must be restarted")
            if time.monotonic() - last_heartbeat >= 60:
                log.write("heartbeat", subscriptions=len(contracts), connected=ib.isConnected())
                last_heartbeat = time.monotonic()
            if time.monotonic() - last_snapshot >= 60:
                # Client 31 need not be the account's master API client. Read-only
                # snapshots cover orders/executions from other clients too; their
                # observation timestamps have up to one minute of polling delay.
                for trade in ib.reqAllOpenOrders():
                    log.write("open_order_snapshot", **order_record(trade))
                for trade in ib.reqCompletedOrders(apiOnly=False):
                    log.write("completed_order_snapshot", **order_record(trade))
                for account in accounts:
                    for fill in ib.reqExecutions(ExecutionFilter(acctCode=account)):
                        log.write("execution_snapshot", **fill_record(fill))
                        report = fill.commissionReport
                        log.write(
                            "commission_snapshot",
                            execution_id=report.execId,
                            commission=report.commission,
                            currency=report.currency,
                        )
                last_snapshot = time.monotonic()
            ib.sleep(1)
    finally:
        for contract in contracts.values():
            ib.cancelMktData(contract)
        ib.disconnect()
        log.write("end")
    print(f"Read-only observations saved under {log.root}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--session", action="store_true")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    capture(args.seconds, args.session)


if __name__ == "__main__":
    main()
