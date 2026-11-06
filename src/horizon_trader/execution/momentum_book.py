"""Large-cap momentum on its own Alpaca PAPER account (keys ALPACA_MOMENTUM_*).

    uv run python -m horizon_trader.execution.momentum_book run [--dry-run]
    uv run python -m horizon_trader.execution.momentum_book status

The rule is the backtest's (`backtest/winners.py`, research/winners_momentum): each month-end,
the 200 largest US companies by point-in-time market cap (Massive), ranked by 12-1 momentum;
hold the top 10 at equal weight. Between month-ends the targets stay 10% each and a position is
traded back once it drifts more than 2% of equity (the backtest's rebalance band).

Timing matches the backtest: signals from a close, fills at the next open. The run belongs in
the 08:00 morning job, after the Massive day download, so it sees yesterday's close (on the
first trading day of a month, the month-end close) and its market DAY orders queue for today's
open. It refuses to send orders during market hours and refuses stale data (the last Massive
day must be the previous session).

Same plumbing as the daily book on Alpaca (`alpaca_book.py`): fills are booked from Alpaca by
client order id, positions must reconcile with the account (it's dedicated), caps and the kill
switch are checked for the whole batch, and the ledger is a virtual $5k in
data/live/momentum_top10_alpaca_paper/. Fractional shares; a name Alpaca can't trade
fractionally gets whole shares. Each formation's ranking is appended to picks.csv.
Known gaps: no dividends; a stock split after the last splits refresh breaks reconcile (it
stops, it doesn't trade through it).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import date, timedelta

import pandas as pd

from horizon_trader.config import ExecutionSettings, LiveSettings
from horizon_trader.execution import alpaca_book as ab
from horizon_trader.execution.ibkr_broker import GuardError
from horizon_trader.execution.ledger import Ledger
from horizon_trader.execution.rebalance import compute_orders

log = logging.getLogger("horizon_trader.momentum")

PREFIX = "ALPACA_MOMENTUM"
LEDGER = "momentum_top10_alpaca_paper"
STARTING_CASH = 5_000.0
TOP = 10
UNIVERSE = 200
LOOKBACK, SKIP = 252, 21  # 12-1 momentum, as winners.SIGNALS["12-1"]
HISTORY = 300  # trading days loaded: the 252-day window plus up to a month since formation
LIMITS = LiveSettings(strategy="momentum_top10", max_order_value=1_500.0, max_orders_per_day=30)
NY = "America/New_York"
SPLIT_COLS = ["ticker", "execution_date", "split_from", "split_to"]


# ---------------------------------------------------------------- signal (pure)


def formation_date(index: pd.DatetimeIndex, today: date) -> pd.Timestamp:
    """The last trading day in `index` before the current calendar month: the month-end close
    the current holdings were formed on."""
    month = pd.Timestamp(today).to_period("M")
    before = index[index.to_period("M") < month]
    if len(before) == 0:
        raise ValueError("no trading day before this month in the data")
    return before[-1]


def rank(adj: pd.DataFrame, universe: list[str], d: pd.Timestamp) -> pd.Series:
    """12-1 momentum at `d` for the universe, best first (NaN-free)."""
    from horizon_trader.backtest.winners import momentum

    mom = momentum(adj.loc[:d], LOOKBACK, SKIP).iloc[-1]
    return mom.reindex(universe).dropna().sort_values(ascending=False)


def targets_from_ranking(ranking: pd.Series, n: int = TOP) -> pd.Series:
    if len(ranking) < n * 2:
        raise ValueError(f"only {len(ranking)} ranked names; need at least {n * 2}")
    return pd.Series(1.0 / n, index=ranking.index[:n])


# ---------------------------------------------------------------- data


def refresh_splits(days: int = 400) -> None:
    """Merge the last `days` of Massive split events into the reference file (cheap REST),
    so a recent split doesn't fake a momentum crash."""
    from horizon_trader.datasources import massive_ref as R

    since = (date.today() - timedelta(days=days)).isoformat()
    new = R.fetch_splits(since=since)
    path = R.ref_path("splits")
    old = pd.read_parquet(path) if path.exists() else new.iloc[:0]
    both = pd.concat([old, new]).drop_duplicates(["ticker", "execution_date"], keep="last")
    both.sort_values(["ticker", "execution_date"], ignore_index=True).to_parquet(path, index=False)


def load_data(today: date) -> dict:
    """Split-adjusted closes (for the ranking) and actual closes/opens of every US common stock
    for the last HISTORY sessions before `today`, the formation date and its universe."""
    from horizon_trader.backtest import megacap as M
    from horizon_trader.datasources import massive, massive_ref
    from horizon_trader.intraday import features as F

    days = [d for d in massive.local_days("day") if d < today][-HISTORY:]
    common = massive_ref.load_common_tickers()
    panels = F.load_daily_panels(days, common)
    splits = massive_ref.load_splits()
    # Massive lists announced splits ahead of time (SNDK 8:1 on 2026-11-20 appeared on
    # 11-05): applying one early would misprice the stock by the split ratio.
    splits = splits[splits["execution_date"] <= pd.Timestamp(today)]
    factor = F.split_factors(panels["close"].index, panels["close"].columns, splits)
    adj = panels["close"] * factor
    d = formation_date(adj.index, today)
    dollar_vol = (panels["close"] * panels["volume"]).rolling(21, min_periods=10).mean()
    cands = dollar_vol.loc[d].dropna().nlargest(M.CANDIDATES).index
    caps = M.market_caps([(t, d.date()) for t in cands])
    universe = list(M.top_n(caps[caps["date"] == d], UNIVERSE).index)
    return {"adj": adj, "close": panels["close"], "open": panels["open"], "formation": d,
            "universe": universe, "caps": caps, "splits": splits}  # fmt: skip


def last_prices(close: pd.DataFrame, symbols, splits: pd.DataFrame | None = None,
                today: date | None = None) -> dict[str, float]:  # fmt: skip
    """Latest actual close per symbol, forward-filled over a halt or a delisting, in TODAY's
    share basis: a split executing after the last close and by `today` (e.g. the morning of
    the split) divides the price by its ratio, matching the split-adjusted position.
    Orders are sized in real shares, so split-adjusted history is for the ranking only."""
    px = close.reindex(columns=sorted(set(symbols))).ffill().iloc[-1]
    missing = px[px.isna()].index.tolist()
    if missing:
        raise GuardError(f"no price for {missing}")
    if splits is not None and today is not None:
        last = close.index[-1]
        new = splits[splits["ticker"].isin(px.index) & (splits["execution_date"] > last)
                     & (splits["execution_date"] <= pd.Timestamp(today))]  # fmt: skip
        for ev in new.itertuples():
            if ev.split_from > 0 and ev.split_to > 0:
                px[ev.ticker] *= ev.split_from / ev.split_to
    return px.to_dict()


def apply_splits(ledger: Ledger, splits: pd.DataFrame, today: date) -> list[str]:
    """Scale held shares by every split executed after the last check and on or before
    `today` (Alpaca adjusts the account's positions; the ledger must follow or reconcile
    stops). splits.json remembers the date checked through and what was applied; the first
    run only starts the clock. Cash is unchanged."""
    path = Ledger.directory(ledger.name, ledger.root) / "splits.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    msgs = []
    if state is not None:
        since = pd.Timestamp(state["through"])
        new = splits[splits["ticker"].isin(ledger.holdings)
                     & (splits["execution_date"] > since)
                     & (splits["execution_date"] <= pd.Timestamp(today))]  # fmt: skip
        for ev in new.itertuples():
            if ev.split_from > 0 and ev.split_to > 0:
                ratio = ev.split_to / ev.split_from
                ledger.holdings[ev.ticker] *= ratio
                msgs.append(f"{ev.ticker} {ev.execution_date:%Y-%m-%d} x{ratio:g}")
    applied = (state or {}).get("applied", []) + msgs
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"through": today.isoformat(), "applied": applied}, indent=1),
                    encoding="utf-8")  # fmt: skip
    return msgs


def previous_session(api, today: date) -> date:
    for back in range(1, 10):
        day = today - timedelta(days=back)
        if api.session(day.isoformat()) is not None:
            return day
    raise GuardError("no session in the last 10 days?")


# ---------------------------------------------------------------- orders


def whole_shares_where_needed(api, orders, ledger: Ledger):
    """Alpaca only takes fractional orders for 'fractionable' assets: round the others to
    whole shares (a sell that closes a position keeps its exact size)."""
    from horizon_trader.execution.broker import Order

    out = []
    for o in orders:
        info = api.asset(o.symbol)
        if not info["tradable"]:
            log.warning("%s isn't tradable at Alpaca; skipped", o.symbol)
            continue
        closing = abs(ledger.holdings.get(o.symbol, 0.0) + o.quantity) < 1e-9
        if info["fractionable"] or closing:
            out.append(o)
            continue
        qty = math.trunc(o.quantity)
        if qty:
            out.append(Order(o.symbol, float(qty), o.order_type))
        else:
            log.warning("%s isn't fractionable and %+.4f rounds to 0 shares", o.symbol, o.quantity)
    return out


def write_picks(ledger: Ledger, data: dict, ranking: pd.Series) -> None:
    path = Ledger.directory(ledger.name, ledger.root) / "picks.csv"
    formation = data["formation"].strftime("%Y-%m-%d")
    if path.exists() and formation in set(pd.read_csv(path, dtype={"formation": str})["formation"]):
        return
    caps = data["caps"][data["caps"]["date"] == data["formation"]]
    names = caps.drop_duplicates("ticker").set_index("ticker")["name"]
    top = ranking.head(TOP * 2)
    df = pd.DataFrame({
        "formation": formation, "rank": range(1, len(top) + 1), "ticker": top.index,
        "name": [names.get(t) for t in top.index], "momentum": top.to_numpy(),
        "selected": [i < TOP for i in range(len(top))],
    })  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, mode="a", header=not path.exists(), index=False)


def run(dry_run: bool = False, api=None, root=None, now: pd.Timestamp | None = None,
        data: dict | None = None) -> tuple[pd.Series, list]:  # fmt: skip
    """`api`, `root`, `now` and `data` exist for tests."""
    from horizon_trader.execution.costs import ibkr_costs
    from horizon_trader.run_daily import market_open

    now = now if now is not None else pd.Timestamp.now(tz=NY)
    today = now.tz_convert(NY).date()
    if not dry_run and market_open(now):
        raise SystemExit("market is open: orders would fill mid-session, not at the open")
    if data is None:
        try:
            refresh_splits()
        except Exception as exc:  # noqa: BLE001 - stale splits are checked by reconcile
            log.warning("splits refresh failed (%r); using the cached file", exc)
        data = load_data(today)
    adj = data["adj"]
    asof = adj.index[-1].strftime("%Y-%m-%d")
    ranking = rank(adj, data["universe"], data["formation"])
    targets = targets_from_ranking(ranking)
    log.info("formation %s, %d ranked; data to %s", data["formation"].date(), len(ranking), asof)
    log.info("targets: %s", ", ".join(targets.index))

    ledger = Ledger.load(LEDGER, STARTING_CASH, root)
    splits = data.get("splits", pd.DataFrame(columns=SPLIT_COLS))
    prices = last_prices(data["close"], set(targets.index) | set(ledger.holdings), splits, today)
    if dry_run:
        orders = compute_orders(targets, ledger.positions(), prices, ledger.equity(prices),
                                ExecutionSettings())  # fmt: skip
        for o in orders:
            log.info("dry run: %+.4f %s @ ~%.2f", o.quantity, o.symbol, prices[o.symbol])
        return targets, orders

    if api is None:
        from horizon_trader.execution.alpaca_broker import AlpacaPaper

        api = AlpacaPaper(PREFIX)
    want = previous_session(api, today)
    if adj.index[-1].date() != want:
        raise GuardError(f"Massive day data ends {asof}, not {want}: download it first")
    broker = ab.AlpacaBookBroker(api, ledger, LIMITS)
    log.info("Alpaca paper account %s, ledger %r", broker.account, ledger.name)
    booked = ab.sync_fills(api, ledger, ibkr_costs("tiered", 0.0), data["open"])
    for msg in apply_splits(ledger, splits, today):
        log.warning("split applied to the ledger: %s", msg)
    ledger.save()
    log.info("%d new fills booked", booked)
    ab.reconcile(api, ledger)
    write_picks(ledger, data, ranking)
    equity = ledger.record_equity(asof, prices)
    log.info(f"equity ${equity:,.2f}, cash ${ledger.cash:,.2f}")
    if any(p.asof == asof for p in ledger.pending):
        log.info("orders for %s were already sent; nothing new", asof)
        return targets, []
    orders = compute_orders(targets, ledger.positions(), prices, ledger.equity(prices),
                            ExecutionSettings())  # fmt: skip
    orders = whole_shares_where_needed(api, orders, ledger)
    for o in orders:
        log.info("%+.4f %s @ ~%.2f", o.quantity, o.symbol, prices[o.symbol])
    broker.submit_all(orders, prices, asof)
    ledger.save()
    log.info("sent %d orders for today's open", len(orders))
    return targets, orders


def status(root=None) -> None:
    ledger = Ledger.load(LEDGER, STARTING_CASH, root)
    folder = Ledger.directory(LEDGER, root)
    eq = folder / "equity.csv"
    print(f"{LEDGER}: cash ${ledger.cash:,.2f}, {len(ledger.holdings)} positions, "
          f"{len(ledger.pending)} orders pending")  # fmt: skip
    for s, q in sorted(ledger.holdings.items()):
        print(f"  {s:6s} {q:10.4f}")
    if eq.exists():
        print(pd.read_csv(eq).tail(5).to_string(index=False))
    pin = folder / "alpaca_account.json"
    if pin.exists():
        print("account", json.loads(pin.read_text(encoding="utf-8"))["account"])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("action", choices=("run", "status"))
    p.add_argument("--dry-run", action="store_true", help="targets and orders, nothing sent")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.action == "status":
        status()
        return
    if not args.dry_run:
        from horizon_trader.config import require_ops

        require_ops("run the momentum book")
    try:
        run(dry_run=args.dry_run)
    except GuardError as e:
        raise SystemExit(f"STOPPED: {e}") from None


if __name__ == "__main__":
    main()
