"""Paper-trade ORB on IBKR: the backtest's baseline, at most one trade a day.

    uv run python -m horizon_trader.intraday.orb_live run [--what-if]   # start before 9:30 ET
    uv run python -m horizon_trader.intraday.orb_live sync              # after the close

The rules are the baseline in research/orb_experiments/README.md, unchanged: rank stocks by
first-5-minute volume / its 14-day mean, apply the paper's filters (open > $5, average volume
>= 1M, ATR > $0.50, relvol >= 1, a non-flat candle), take the top 1, enter on a break of the
opening range in the candle's direction with a stop-limit at the trigger price, stop 1 ATR
away, exit at the close. Size: 1% of equity at risk, at most 4x equity. Equity is the `orb`
ledger's virtual $5k, never the paper account's $1M.

Known differences from the backtest:
  1. Candidates come from IBKR's 9:35 "5min Volume vs Average Volume" scanner (50 names),
     which held the backtest's pick on 98% of days in Experiment 11's proxy.
  2. The opening range and its volume come from IBKR's 1-minute bars, not Massive's.
  3. No entries after 15:44 (GTD), so the market-on-close exit can still be sent.
  4. History ends at the last day with Massive files on disk (normally yesterday).

`run` places the entry (STP LMT, GTD 15:44) with an attached 1-ATR stop child, then stays
up. At 15:45 it cancels the working orders, reads the ACTUAL position from IBKR and sends a
market-on-close for it; if IBKR rejects the MOC it sends a market order at once. At 16:01 it
checks the position again and sends an urgent alert if it isn't flat. (IBKR rejected a MOC
child inside the bracket's OCA group with "Invalid OCA handling method", 2026-11-10.)
All waits run IBKR's event loop (ib.sleep), so order and fill updates keep arriving.
If the ledger starts the day holding anything (a failed exit), `run` first sends market
orders to close it at the open (OPG before 09:28), and skips a pick in the same ticker.
`sync` books the day's fills into the ledger (IBKR's commission next to the model's) and
checks the account is flat. IBKR returns only the current day's executions, so run it the
same evening. PAPER ONLY: the account guard and kill switch from execution.ibkr_broker apply.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import date

import pandas as pd

from horizon_trader.config import data_dir, load_settings
from horizon_trader.datasources import massive, massive_ref
from horizon_trader.execution.costs import ibkr_costs
from horizon_trader.execution.ledger import Ledger
from horizon_trader.intraday import features as F
from horizon_trader.intraday import orb

RULES = replace(orb.RULES, stop_atr=1.0)
ACCOUNT = orb.Account(equity=5_000.0, top_n=1, plan="tiered")  # 1% risk, 4x cap
STRATEGY = "orb"
CLIENT_ID = 21
NY = "America/New_York"
SCAN = ("SCAN_stVolumeVsAvg5min_DESC", "CORP")
SCAN_AT = "09:35:05"
ENTRY_CUTOFF = "15:44:00"
EXIT_AT = "15:45:00"  # NYSE/Nasdaq take MOC orders until 15:50
FLAT_CHECK = "16:01:00"
OPG_BY = "09:28:00"  # IBKR takes market-on-open orders until 09:28
REJECTED = {"Cancelled", "ApiCancelled", "Inactive"}


# ---------------------------------------------------------------- pure pieces (tested)


def todays_features(
    panels: dict[str, pd.DataFrame],
    or_volume: pd.DataFrame,
    splits: pd.DataFrame,
    asof: date,
    lookback: int = RULES.lookback,
) -> pd.DataFrame:
    """atr, avg_volume, prev_close and the 14-day mean opening-range volume for `asof`,
    from days before it, in asof's share basis: the same numbers the backtest uses."""
    t = pd.Timestamp(asof)
    idx = panels["open"].index.append(pd.DatetimeIndex([t]))
    ext = {k: v.reindex(idx) for k, v in panels.items()}
    factor = F.split_factors(idx, ext["open"].columns, splits)
    feats = F.daily_features(ext, factor, lookback)
    traded = ext["volume"].fillna(0) > 0
    vol = (or_volume.reindex(index=idx, columns=factor.columns).fillna(0.0) / factor).where(traded)
    hist = vol.rolling(lookback, min_periods=lookback).mean().shift(1).loc[t]
    out = pd.DataFrame({k: feats[k].loc[t] for k in ("atr", "avg_volume", "prev_close")})
    out["or_vol_mean"] = hist.where(hist > 0)
    return out.dropna(subset=["atr", "avg_volume", "or_vol_mean"])


def pick(feats: pd.DataFrame, ors: pd.DataFrame) -> pd.DataFrame:
    """Rank today's scanned stocks exactly like orb.select_candidates (top row = the trade)."""
    day = feats.join(ors, how="inner")
    day["open"] = day["or_open"]
    day["relvol"] = day["or_volume"] / day["or_vol_mean"]
    return orb.select_candidates(day, RULES)


@dataclass(frozen=True)
class Plan:
    ticker: str
    side: int
    level: float
    stop_px: float
    qty: int
    atr: float
    relvol: float


def plan_trade(c: pd.Series, equity: float, acct: orb.Account = ACCOUNT) -> Plan | None:
    """Size like orb.run_portfolio: 1% risk per ATR stop, at most leverage x equity."""
    side = int(c["side"])
    level = round(float(c["or_high"] if side > 0 else c["or_low"]), 2)
    stop_dist = RULES.stop_atr * float(c["atr"])
    qty = math.floor(
        min(acct.risk * equity / stop_dist, acct.leverage * equity / acct.top_n / level)
    )
    if qty < 1:
        return None
    stop_px = round(level - side * stop_dist, 2)
    return Plan(str(c.name), side, level, stop_px, qty, float(c["atr"]), float(c["relvol"]))


def bracket(plan: Plan, account: str, ids: tuple[int, int], day: date) -> list:
    """Entry stop-limit at the trigger (GTD 15:44) + an attached 1-ATR stop child. The close
    is sent by the runner at 15:45 for the position IBKR actually reports (`manage_exit`)."""
    from ib_async import Order

    act, close_act = ("BUY", "SELL") if plan.side > 0 else ("SELL", "BUY")
    common = dict(totalQuantity=plan.qty, orderRef=STRATEGY, account=account)
    return [
        Order(
            orderId=ids[0], action=act, orderType="STP LMT", auxPrice=plan.level,
            lmtPrice=plan.level, tif="GTD", goodTillDate=f"{day:%Y%m%d} {ENTRY_CUTOFF} US/Eastern",
            transmit=False, **common,
        ),
        Order(
            orderId=ids[1], parentId=ids[0], action=close_act, orderType="STP",
            auxPrice=plan.stop_px, tif="DAY", transmit=True, **common,
        ),
    ]  # fmt: skip


def close_order(position: float, account: str, order_type: str = "MOC", tif: str = "DAY"):
    """A market-type order that flattens `position` (signed shares), tagged for the ledger."""
    from ib_async import Order

    return Order(
        action="SELL" if position > 0 else "BUY", totalQuantity=abs(position),
        orderType=order_type, tif=tif, orderRef=STRATEGY, account=account, transmit=True,
    )  # fmt: skip


# ---------------------------------------------------------------- IO


def history(asof: date) -> pd.DataFrame:
    """todays_features from the Massive files on disk (the last 15 days with both files)."""
    minute = set(massive.local_days("minute"))
    days = [d for d in massive.local_days("day") if d < asof and d in minute][-15:]
    common = massive_ref.load_common_tickers()
    panels = F.load_daily_panels(days, common)
    ors = orb.opening_ranges(days, common, RULES.minutes)
    or_vol = ors.pivot(index="date", columns="ticker", values="or_volume")
    feats = todays_features(panels, or_vol, massive_ref.load_splits(), asof)
    feats.attrs["history_ends"] = str(days[-1])
    return feats


def fetch_or_bars(ib, contracts: list) -> pd.DataFrame:
    """Today's regular-session 1-minute bars so far, long format like the Massive files."""

    async def one(c):
        return await ib.reqHistoricalDataAsync(
            c, endDateTime="", durationStr="900 S", barSizeSetting="1 min",
            whatToShow="TRADES", useRTH=True, formatDate=2,
        )  # fmt: skip

    rows = []
    for i in range(0, len(contracts), 25):  # IBKR allows ~50 open historical requests
        chunk = contracts[i : i + 25]
        results = ib.run(asyncio.gather(*(one(c) for c in chunk), return_exceptions=True))
        for c, bars in zip(chunk, results, strict=True):
            if isinstance(bars, BaseException) or not bars:
                continue
            for b in bars:
                rows.append(
                    {"ts": pd.Timestamp(b.date).tz_convert(NY), "ticker": c.symbol,
                     "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                     "volume": float(b.volume)}
                )  # fmt: skip
    return pd.DataFrame(rows, columns=["ts", "ticker", "open", "high", "low", "close", "volume"])


def _wait_until(day: date, hhmmss: str, ib=None) -> None:
    """Sleep until `hhmmss` ET. With `ib`, sleep through ib.sleep so the event loop keeps
    processing order/fill updates (time.sleep froze them for 6 hours on 2026-11-10, and the
    runner then believed an entry that had filled was unfilled), and fail fast on a drop."""
    until = pd.Timestamp(f"{day} {hhmmss}", tz=NY)
    wait = (until - pd.Timestamp.now(tz=NY)).total_seconds()
    if wait <= 0:
        return
    print(f"waiting {wait / 60:.0f} min for {hhmmss} ET", flush=True)
    if ib is None:
        time.sleep(wait)
        return
    while (left := (until - pd.Timestamp.now(tz=NY)).total_seconds()) > 0:
        if not ib.isConnected():
            raise ConnectionError(f"IBKR disconnected while waiting for {hhmmss} ET")
        ib.sleep(min(30.0, left))


def _day_log(day: date) -> tuple[dict, Callable[[], None]]:
    path = Ledger.directory(STRATEGY) / "days" / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    log: dict = {}

    def save() -> None:
        path.write_text(json.dumps(log, indent=1, default=str), encoding="utf-8")

    return log, save


def trades_through_ibkr(folder) -> bool:
    """Shadow ledgers trade nowhere; Alpaca ledgers (pinned account file, the competition's
    follow.json, or "alpaca" in the name) hold positions IBKR never sees."""
    name = folder.name
    return not (
        name.endswith("_shadow")
        or "alpaca" in name
        or (folder / "alpaca_account.json").exists()
        or (folder / "follow.json").exists()
    )


def ibkr_ledgers() -> list[Ledger]:
    """Every strategy ledger that trades through IBKR, for reconcile against its positions."""
    root = data_dir() / "live"
    names = [p.parent.name for p in root.glob("*/state.json") if trades_through_ibkr(p.parent)]
    return [Ledger.load(n, 0.0) for n in sorted(set(names) | {STRATEGY})]


def scan_and_plan(ib, day: date, feats: pd.DataFrame, equity: float, log: dict):
    """At 09:35:05: IBKR scanner -> today's 1-minute bars -> exact relvol ranking -> sized
    plan. Returns (plan, contract), or (None, None) with log["decision"] saying why. Shared by
    the IBKR executor (`run`) and the Alpaca one (`orb_alpaca`), so both trade the same pick."""
    from ib_async import Stock

    from horizon_trader.intraday.scanner_log import run_scan

    _wait_until(day, SCAN_AT, ib)
    ib.RequestTimeout = 30
    symbols = run_scan(ib, *SCAN)
    log["scanner"] = {"at": pd.Timestamp.now(tz=NY), "symbols": symbols}
    contracts = [c for c in ib.qualifyContracts(*[Stock(s, "SMART", "USD") for s in symbols]) if c]
    bars = fetch_or_bars(ib, contracts)
    ors = F.opening_range(bars, day, RULES.minutes)
    cands = pick(feats, ors)
    log["candidates"] = cands.reset_index().head(10).to_dict("records")
    print(f"{len(symbols)} scanned, {len(ors)} with bars, {len(cands)} candidates", flush=True)
    if cands.empty:
        log["decision"] = "no candidate"
        return None, None
    plan = plan_trade(cands.iloc[0], equity)
    if plan is None:
        log["decision"] = "size below 1 share"
        return None, None
    log["plan"] = asdict(plan) | {"equity": equity}
    print(f"plan: {plan}", flush=True)
    return plan, next(c for c in contracts if c.symbol == plan.ticker)


def run(what_if: bool) -> None:
    from horizon_trader.execution.ibkr import connect
    from horizon_trader.execution.ibkr_broker import (
        GuardError,
        kill_switch_path,
        paper_account,
        reconcile,
    )

    day = pd.Timestamp.now(tz=NY).date()
    if day.weekday() >= 5:
        print("weekend: nothing to do")
        return
    log, save = _day_log(day)
    feats = history(day)
    log["history_ends"] = feats.attrs["history_ends"]
    print(f"history through {log['history_ends']}: {len(feats)} stocks with 14 days", flush=True)

    ib = connect(readonly=False, client_id=CLIENT_ID)
    try:
        account = paper_account(ib)
        if kill_switch_path().exists():
            raise GuardError(f"kill switch is on ({kill_switch_path()})")
        reconcile(ib, account, ibkr_ledgers())  # ledger and account agree (incl. leftovers)
        ledger = Ledger.load(STRATEGY, ACCOUNT.equity)
        leftovers = {s: q for s, q in ledger.holdings.items() if q}
        equity = ledger.cash + leftover_value(leftovers, feats)
        if leftovers and not what_if:
            close_leftovers(ib, account, leftovers, log)
            save()

        plan, contract = scan_and_plan(ib, day, feats, equity, log)
        if plan is None:
            return
        if plan.ticker in leftovers:
            log["skipped_plan"] = log.pop("plan", None)  # orb_alpaca follows log["plan"]
            log["decision"] = f"pick {plan.ticker} is a leftover being closed; no trade"
            print(log["decision"], flush=True)
            return
        notional = plan.qty * plan.level
        if notional > ACCOUNT.leverage * equity * 1.01:
            raise GuardError(f"notional ${notional:,.0f} over {ACCOUNT.leverage}x ${equity:,.0f}")
        if kill_switch_path().exists():
            raise GuardError(f"kill switch is on ({kill_switch_path()})")

        if what_if:
            entry = bracket(plan, account, (0, 0), day)[0]
            entry.transmit = True
            state = ib.whatIfOrder(contract, entry)
            log["what_if"] = {"commission": getattr(state, "commission", None),
                              "init_margin": getattr(state, "initMarginChange", None),
                              "warning": getattr(state, "warningText", None)}  # fmt: skip
            log["decision"] = "what-if only"
            print("what-if:", log["what_if"])
            return

        ids = (ib.client.getReqId(), ib.client.getReqId())
        trades = [ib.placeOrder(contract, o) for o in bracket(plan, account, ids, day)]
        ib.sleep(3)
        status = {t.order.orderType: t.orderStatus.status for t in trades}
        log["orders"] = {"ids": ids, "status": status}
        print("orders:", status, flush=True)
        if status["STP LMT"] in REJECTED or status["STP"] in REJECTED:
            for t in trades:
                if not t.isDone():
                    ib.cancelOrder(t.order)
            msgs = "; ".join(t.log[-1].message for t in trades if t.log and t.log[-1].message)
            raise GuardError(f"bracket rejected: {status} {msgs}")
        log["decision"] = "placed; runner manages the 15:45 exit"
        save()
        manage_exit(ib, account, contract, trades, day, log, save)
    finally:
        save()
        ib.disconnect()


def ibkr_position(ib, account: str, contract) -> float:
    """Signed shares IBKR reports right now for this contract (fresh request, not a cache)."""
    return sum(
        p.position
        for p in ib.reqPositions()
        if p.account == account and p.contract.conId == contract.conId
    )


def manage_exit(ib, account: str, contract, trades: list, day: date, log: dict, save) -> None:
    """15:45: cancel the entry and stop, read the real position, MOC it (market order if the
    MOC is rejected). 16:01: confirm flat, else alert. The position, not order bookkeeping,
    decides: a stop or entry can fill while the cancels are in flight."""
    _wait_until(day, EXIT_AT, ib)
    for t in trades:
        if not t.isDone():
            ib.cancelOrder(t.order)
    deadline = time.monotonic() + 30
    while not all(t.isDone() for t in trades) and time.monotonic() < deadline:
        ib.sleep(1)
    held = ibkr_position(ib, account, contract)
    log["exit"] = {"position_at_exit": held}
    if not held:
        log["decision"] = "flat at 15:45 (no fill or stopped out)"
        print(log["decision"], flush=True)
        save()
        return
    exit_trade = ib.placeOrder(contract, close_order(held, account, "MOC"))
    ib.sleep(5)
    log["exit"]["moc"] = exit_trade.orderStatus.status
    print(f"sent MOC for {held:g} {contract.symbol}: {exit_trade.orderStatus.status}", flush=True)
    if exit_trade.orderStatus.status in REJECTED:
        msg = exit_trade.log[-1].message if exit_trade.log else ""
        print(f"MOC rejected ({msg}); sending a market order now", flush=True)
        mkt = ib.placeOrder(contract, close_order(held, account, "MKT"))
        ib.sleep(5)
        log["exit"]["market"] = mkt.orderStatus.status
    save()
    _wait_until(day, FLAT_CHECK, ib)
    left = ibkr_position(ib, account, contract)
    log["exit"]["position_after_close"] = left
    if left:
        log["decision"] = f"NOT FLAT after the close: {left:g} {contract.symbol}"
        alert(f"ORB (IBKR paper) not flat: {left:g} {contract.symbol}",
              "The runner closes it at the next open. Check IB Gateway.")  # fmt: skip
    else:
        log["decision"] = "closed at the close"
    print(log["decision"], flush=True)
    save()


def leftover_value(leftovers: dict[str, float], feats: pd.DataFrame) -> float:
    """Leftover shares at the previous close, so sizing sees the whole ledger equity."""
    total = 0.0
    for symbol, qty in leftovers.items():
        px = feats["prev_close"].get(symbol) if "prev_close" in feats else None
        total += qty * float(px) if px is not None and not pd.isna(px) else 0.0
    return total


def close_leftovers(ib, account: str, leftovers: dict[str, float], log: dict) -> None:
    """Market-on-open (or a day market order after 09:28) for positions a failed exit left
    overnight. The evening `sync` books the fills like any other ORB execution."""
    from ib_async import Stock

    from horizon_trader.execution.ibkr_broker import GuardError

    now = pd.Timestamp.now(tz=NY)
    opg = now < pd.Timestamp(f"{now.date()} {OPG_BY}", tz=NY)
    sent = {}
    for symbol, qty in leftovers.items():
        (contract,) = ib.qualifyContracts(Stock(symbol, "SMART", "USD"))
        order = close_order(qty, account, "MKT", "OPG" if opg else "DAY")
        trade = ib.placeOrder(contract, order)
        ib.sleep(2)
        status = trade.orderStatus.status
        sent[symbol] = {"qty": -qty, "tif": order.tif, "status": status}
        print(f"leftover {symbol} {qty:g}: sent {order.action} {abs(qty):g} MKT {order.tif} "
              f"({status})", flush=True)  # fmt: skip
        if status in REJECTED:
            log["leftovers"] = sent
            raise GuardError(f"leftover close for {symbol} rejected")
    log["leftovers"] = sent


def alert(title: str, body: str = "") -> None:
    """Urgent Discord/ntfy alert; never let a missing channel break the runner."""
    try:
        from horizon_trader.ops.notify import send

        send(title, body, "urgent")
    except BaseException as exc:  # noqa: BLE001 - SystemExit when no channel is configured
        print(f"(alert not sent: {exc!r})", flush=True)


def sync() -> None:
    from horizon_trader.execution.ibkr import connect
    from horizon_trader.execution.ibkr_broker import paper_account, reconcile, sync_fills

    settings = load_settings()
    costs = ibkr_costs(settings.costs.plan, 0.0)
    ib = connect(readonly=False, client_id=CLIENT_ID)
    try:
        account = paper_account(ib)
        ledger = Ledger.load(STRATEGY, ACCOUNT.equity)
        n = sync_fills(ib, ledger, costs)
        ledger.save()
        day = pd.Timestamp.now(tz=NY).strftime("%Y-%m-%d")
        print(f"{n} fills booked; {STRATEGY} cash ${ledger.cash:,.2f}")
        if ledger.holdings:
            print(f"WARNING: not flat after the close: {ledger.holdings}")
            alert(f"ORB (IBKR paper) ledger not flat: {ledger.holdings}",
                  "The next run closes it at the open.")  # fmt: skip
        else:
            ledger.record_equity(day, {})
        reconcile(ib, account, ibkr_ledgers())
    finally:
        ib.disconnect()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("action", choices=("run", "sync"))
    p.add_argument("--what-if", action="store_true", help="ask IBKR for margin/commission only")
    args = p.parse_args()
    from horizon_trader.config import require_ops
    from horizon_trader.execution.ibkr_broker import GuardError

    require_ops(f"orb_live {args.action}")

    try:
        run(args.what_if) if args.action == "run" else sync()
    except GuardError as e:
        raise SystemExit(f"STOPPED: {e}") from None


if __name__ == "__main__":
    main()
