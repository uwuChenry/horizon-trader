"""QQQ noise-area intraday momentum on its own Alpaca PAPER account (keys ALPACA_QQQ_NOISE_*).

    uv run python -m horizon_trader.intraday.noise_live run     # start before 10:00 ET; ends ~16:05
    uv run python -m horizon_trader.intraday.noise_live check   # today's bands + signal, no orders
    uv run python -m horizon_trader.intraday.noise_live status

The rule is `intraday/market_momentum.py` at the paper's defaults (Zarattini, Aziz & Barbon
2024; research/strategy_survey, the QQQ robustness check), nothing tuned:
  band      sigma(m) = mean over the previous 14 sessions of |price at minute m / open - 1|
            upper = max(open, prev close) * (1 + sigma), lower = min(open, prev close) * (1 - sigma)
  checks    10:00, 10:30, ..., 15:30 on the close of the minute ending then
  position  long above max(upper, VWAP), short below min(lower, VWAP), else flat
  size      2% daily vol target on the previous 14 sessions' close-to-close vol, at most 4x,
            whole shares from the start-of-day equity, the same size all day
  exit      whatever is open after the last check goes out market-on-close

Data: sigma, the previous close and the daily vol come from the Massive minute/day files (the
08:00 job downloads yesterday's); the run refuses to trade if they don't end on the previous
session. Today's open, the check prices and the session VWAP ((H+L+C)/3 x volume, as the
backtest) come from IBKR's live consolidated 1-minute bars (read-only, client id 41), or from
Alpaca's free IEX bars when IBKR fails; each check logs its source. IBKR's first-minute open
stands in for the official opening print.

Orders: Alpaca paper market orders, sent right after each check (the backtest fills at the
next minute's open). A reversal is two orders, exit then entry (Alpaca won't flip a position
in one). Client order ids are `qqqnoise-<date>-<HHMM>-x|e` and `-moc`, so a restarted run books
what already happened and never resends. The kill switch (data/live/KILL) blocks entries; exits
and the closing order still go out. Ledger: data/live/qqq_noise_alpaca_paper/ (virtual $5k),
with every check in checks.jsonl. Alpaca paper fills are simulated; the ledger logs the IBKR
Tiered commission alongside for comparison.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from horizon_trader.config import LiveSettings
from horizon_trader.execution.ibkr_broker import GuardError
from horizon_trader.execution.ledger import Ledger
from horizon_trader.intraday import market_momentum as MM

log = logging.getLogger("horizon_trader.noise")

TICKER = "QQQ"
PREFIX = "ALPACA_QQQ_NOISE"
LEDGER = "qqq_noise_alpaca_paper"
STARTING_CASH = 5_000.0
VOL_TARGET, MAX_LEVERAGE = 0.02, 4.0  # MM.Account defaults
IB_CLIENT_ID = 41
LIMITS = LiveSettings(strategy="qqq_noise", max_order_value=25_000.0, max_orders_per_day=30)
NY = "America/New_York"
FILL_WAIT = 90  # seconds to wait for a market order to finish
MOC_CUTOFF = 10  # Alpaca takes market-on-close orders until 10 minutes before the close


# ---------------------------------------------------------------- plan (pure)


@dataclass
class DayPlan:
    day: str
    session_len: int  # minutes (390, or 210 on a 13:00 half day)
    prev_close: float
    vol: float  # previous 14 sessions' daily close-to-close std
    sigma: dict[int, float]  # check bar index j -> band width
    history_end: str  # last Massive session used

    @property
    def checks(self) -> list[int]:
        return [j for j in MM.CHECKS if j + 1 < self.session_len]

    def leverage(self) -> float:
        return min(MAX_LEVERAGE, VOL_TARGET / self.vol) if self.vol > 0 else 0.0

    def shares(self, equity: float, open_price: float) -> int:
        return int(math.floor(equity * self.leverage() / open_price)) if open_price > 0 else 0


def plan_day(minute: pd.DataFrame, daily: pd.DataFrame, day: str, session_len: int,
             lookback: int = MM.LOOKBACK) -> DayPlan:  # fmt: skip
    """Today's bands from history strictly before `day`, exactly as the backtest's row for
    `day` (noise_sigma = rolling mean shifted one day; daily_vol likewise)."""
    bars = MM.make_bars(minute[minute["date"] < pd.Timestamp(day)],
                        daily[daily["date"] < pd.Timestamp(day)])  # fmt: skip
    move = (bars.close.div(bars.daily["open"], axis=0) - 1).abs().iloc[-lookback:]
    ok = move.notna().sum() >= lookback - 2
    sigma = move.mean().where(ok)
    closes = bars.daily["close"]
    vol = float(closes.pct_change().iloc[-lookback:].std())
    return DayPlan(
        day=day, session_len=session_len, prev_close=float(closes.iloc[-1]), vol=vol,
        sigma={j: float(sigma[j]) for j in MM.CHECKS if np.isfinite(sigma[j])},
        history_end=bars.close.index[-1].strftime("%Y-%m-%d"),
    )  # fmt: skip


def signal(live: pd.DataFrame, j: int, plan: DayPlan) -> dict:
    """The check at bar j on today's live bars (index = bar j from 9:30, columns open, high,
    low, close, volume): price, bands, VWAP and the target position (-1, 0, +1)."""
    upto = live[live.index <= j]
    if upto.empty or j not in plan.sigma:
        return {"j": j, "target": 0, "note": "no bars yet" if upto.empty else "no sigma"}
    day_open = float(live["open"].iloc[0])
    price = float(upto["close"].iloc[-1])
    typical = (upto["high"] + upto["low"] + upto["close"]) / 3
    vol = upto["volume"].sum()
    vwap = float((typical * upto["volume"]).sum() / vol) if vol > 0 else np.nan
    s = plan.sigma[j]
    upper = max(day_open, plan.prev_close) * (1 + s)
    lower = min(day_open, plan.prev_close) * (1 - s)
    target = int(MM.noise_targets([price], [upper], [lower], [vwap])[0])
    return {"j": j, "open": day_open, "price": price, "upper": upper, "lower": lower,
            "vwap": vwap, "sigma": s, "target": target,
            "last_bar": int(upto.index[-1])}  # fmt: skip


def hhmm(j: int) -> str:
    """Wall-clock time at the END of bar j (j=29 -> '1000')."""
    t = pd.Timestamp("2000-01-01 09:30") + pd.Timedelta(minutes=j + 1)
    return t.strftime("%H%M")


# ---------------------------------------------------------------- live data


def _to_frame(rows: list[dict], open_ts: pd.Timestamp, now: pd.Timestamp) -> pd.DataFrame:
    """Rows with a NY `ts` (bar start) -> finished bars indexed by j."""
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    ts = pd.to_datetime(df["ts"])
    ts = ts.dt.tz_convert(NY) if ts.dt.tz is not None else ts.dt.tz_localize(NY)
    df["j"] = ((ts - open_ts) // pd.Timedelta(minutes=1)).astype(int)
    done = ts + pd.Timedelta(minutes=1) <= now
    df = df[(df["j"] >= 0) & done].drop_duplicates("j", keep="last").set_index("j").sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


class IBKRBars:
    name = "ibkr"

    def __init__(self, client_id: int = IB_CLIENT_ID):
        self.client_id = client_id

    def bars(self, open_ts: pd.Timestamp, now: pd.Timestamp) -> pd.DataFrame:
        from ib_async import Stock

        from horizon_trader.execution.ibkr import connect

        ib = connect(readonly=True, client_id=self.client_id)
        try:
            ib.RequestTimeout = 20
            bars = ib.reqHistoricalData(
                Stock(TICKER, "SMART", "USD"), endDateTime="", durationStr="1 D",
                barSizeSetting="1 min", whatToShow="TRADES", useRTH=True, formatDate=2,
            )  # fmt: skip
        finally:
            ib.disconnect()
        rows = [{"ts": pd.Timestamp(b.date).tz_convert(NY), "open": b.open, "high": b.high,
                 "low": b.low, "close": b.close, "volume": b.volume} for b in bars]  # fmt: skip
        rows = [r for r in rows if r["ts"].date() == open_ts.date()]
        return _to_frame(rows, open_ts, now)


class AlpacaBars:
    name = "alpaca-iex"

    def __init__(self, api):
        self.api = api

    def bars(self, open_ts: pd.Timestamp, now: pd.Timestamp) -> pd.DataFrame:
        return _to_frame(self.api.minute_bars(TICKER, open_ts.to_pydatetime()), open_ts, now)


def live_bars(feeds, open_ts, now) -> tuple[pd.DataFrame, str]:
    errors = []
    for feed in feeds:
        try:
            df = feed.bars(open_ts, now)
            if len(df):
                return df, feed.name
            errors.append(f"{feed.name}: no bars")
        except Exception as exc:  # noqa: BLE001 - try the next source
            errors.append(f"{feed.name}: {exc!r}"[:200])
    raise RuntimeError("; ".join(errors))


# ---------------------------------------------------------------- runner


def append_event(path, clock, kind: str, **fields) -> None:
    row = {"time": clock.now().isoformat(), "kind": kind, **fields}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


class Clock:
    def now(self) -> pd.Timestamp:
        return pd.Timestamp.now(tz=NY)

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class Runner:
    def __init__(self, api, feeds, ledger: Ledger, plan: DayPlan, open_ts: pd.Timestamp,
                 clock=None, broker=None):  # fmt: skip
        from horizon_trader.execution.costs import ibkr_costs

        self.api, self.feeds, self.ledger, self.plan = api, feeds, ledger, plan
        self.open_ts, self.clock = open_ts, clock or Clock()
        self.close_ts = open_ts + pd.Timedelta(minutes=plan.session_len)
        self.costs = ibkr_costs("tiered", 0.0)
        self.broker = broker
        self.qty = 0  # shares per position, set at the first check
        self.equity0 = ledger.equity({TICKER: plan.prev_close})
        self.log_path = Ledger.directory(ledger.name, ledger.root) / "checks.jsonl"

    def cid(self, tag: str) -> str:
        return f"qqqnoise-{self.plan.day}-{tag}"

    def write(self, kind: str, **fields) -> None:
        append_event(self.log_path, self.clock, kind, **fields)

    @property
    def position(self) -> float:
        return self.ledger.holdings.get(TICKER, 0.0)

    # -- orders --------------------------------------------------------------------------
    def book(self, cid: str, info, ref_price: float, sign: float | None = None) -> None:
        """Book a finished order once. `sign` is the side we sent (+ buy); after a restart
        it comes from Alpaca's leg."""
        if info.filled_qty <= 0 or cid in self.ledger.seen_exec_ids:
            return
        if sign is None:
            sign = 1.0 if info.legs and info.legs[0].side == "buy" else -1.0
        qty = math.copysign(info.filled_qty, sign)
        when = info.filled_at or self.clock.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ledger.apply_fill(
            time=when, source="alpaca", symbol=TICKER, quantity=qty, price=float(info.avg_price),
            commission=0.0, modeled_commission=self.costs.total(qty, float(info.avg_price)),
            ref_price=ref_price, exec_id=cid,
        )  # fmt: skip
        self.ledger.save()

    def wait(self, cid: str, until: pd.Timestamp):
        info = self.api.order(cid)
        while info is not None and not info.final and self.clock.now() < until:
            self.clock.sleep(1)
            info = self.api.order(cid)
        return info

    def send(self, tag: str, qty: float, ref_price: float, tif: str = "day"):
        """Send (or find, after a restart) one market order and book its fill."""
        from horizon_trader.execution.alpaca_broker import Leg, OrderSpec

        cid = self.cid(tag)
        info = self.api.order(cid)
        if info is None:
            side = "buy" if qty > 0 else "sell"
            info = self.api.submit(OrderSpec(cid, (Leg(TICKER, side),), abs(qty), None, tif))
            self.write("order", cid=cid, qty=qty, tif=tif, status=info.status)
        if tif == "cls":
            return info
        info = self.wait(cid, self.clock.now() + pd.Timedelta(seconds=FILL_WAIT))
        if info is None or not info.final:
            self.write("order_unfinished", cid=cid, status=getattr(info, "status", None))
            log.error("%s not finished after %ss", cid, FILL_WAIT)
            return info
        self.book(cid, info, ref_price, qty)
        if info.filled_qty <= 0:
            self.write("order_unfilled", cid=cid, status=info.status)
            log.warning("%s ended %s unfilled", cid, info.status)
        return info

    def recover(self) -> None:
        """Book anything today's earlier run already sent (restart after a crash)."""
        for j in self.plan.checks:
            for leg in ("x", "e"):
                cid = self.cid(f"{hhmm(j)}-{leg}")
                info = self.api.order(cid)
                if info is not None and info.final:
                    self.book(cid, info, math.nan)

    # -- the day -------------------------------------------------------------------------
    def entries_allowed(self, qty: float, price: float) -> bool:
        if self.broker is None:
            return True
        from horizon_trader.execution.broker import Order

        try:
            self.broker.check([Order(TICKER, qty)], {TICKER: price})
            return True
        except GuardError as e:
            self.write("entry_blocked", reason=str(e))
            log.warning("entry blocked: %s", e)
            return False

    def at_check(self, j: int) -> dict:
        now = self.clock.now()
        try:
            live, source = live_bars(self.feeds, self.open_ts, now)
        except RuntimeError as e:
            self.write("check", j=j, at=hhmm(j), error=str(e))
            log.error("check %s: no data (%s); position kept", hhmm(j), e)
            return {"j": j, "error": str(e)}
        sig = signal(live, j, self.plan) | {"source": source, "at": hhmm(j)}
        if not self.qty and "open" in sig:
            self.qty = self.plan.shares(self.equity0, sig["open"])
            self.write("size", equity=self.equity0, leverage=self.plan.leverage(), qty=self.qty)
        pos = int(np.sign(self.position))
        sig |= {"position": pos, "qty": self.qty}
        self.write("check", **sig)
        log.info("%s %s price %.2f band [%.2f, %.2f] vwap %.2f -> target %+d (pos %+d)",
                 sig["at"], source, sig.get("price", np.nan), sig.get("lower", np.nan),
                 sig.get("upper", np.nan), sig.get("vwap", np.nan), sig["target"], pos)  # fmt: skip
        target = sig["target"]
        if target == pos:
            return sig
        price = sig.get("price", np.nan)
        if pos:
            self.send(f"{hhmm(j)}-x", -self.position, price)
        if target and self.qty >= 1 and self.entries_allowed(target * self.qty, price):
            self.send(f"{hhmm(j)}-e", target * self.qty, price)
        return sig

    def close_out(self) -> None:
        if not self.position:
            return
        now = self.clock.now()
        if now < self.close_ts - pd.Timedelta(minutes=MOC_CUTOFF):
            self.send("moc", -self.position, math.nan, tif="cls")
        else:  # too late for a closing order: flatten now
            self.send("late-x", -self.position, math.nan)

    def finish(self) -> None:
        cid = self.cid("moc")
        info = self.wait(cid, self.close_ts + pd.Timedelta(minutes=10))
        if info is not None and info.final:
            self.book(cid, info, math.nan, -self.position)
        if self.position:
            self.write("not_flat", position=self.position)
            log.error("still %+g %s after the close: check the account", self.position, TICKER)

    def run(self) -> None:
        self.write("start", plan=asdict(self.plan), position=self.position, equity=self.equity0)
        for j in self.plan.checks:
            at = self.open_ts + pd.Timedelta(minutes=j + 1)
            now = self.clock.now()
            if now > at + pd.Timedelta(minutes=10):
                continue  # passed (late start or restart): act at the next check
            self.clock.sleep((at - now).total_seconds() + 3)  # let the bar finish
            self.at_check(j)
        self.close_out()
        self.clock.sleep((self.close_ts - self.clock.now()).total_seconds() + 60)
        self.finish()


def previous_session(api, day: date) -> date:
    for back in range(1, 10):
        d = day - timedelta(days=back)
        if api.session(d.isoformat()) is not None:
            return d
    raise GuardError("no session in the last 10 days?")


def setup(api, today: date):
    """(plan, open_ts) or (None, reason)."""
    sess = api.session(today.isoformat())
    if sess is None:
        return None, "market closed today"
    open_ts = pd.Timestamp(f"{today} {sess[0]}", tz=NY)
    close_ts = pd.Timestamp(f"{today} {sess[1]}", tz=NY)
    session_len = int((close_ts - open_ts) / pd.Timedelta(minutes=1))
    minute, daily = MM.load_bars(TICKER)
    plan = plan_day(minute, daily, today.isoformat(), session_len)
    want = previous_session(api, today).isoformat()
    if plan.history_end != want:
        return None, f"Massive history ends {plan.history_end}, not {want}: no trading today"
    return (plan, open_ts), ""


def run(api=None, feeds=None, root=None, clock=None) -> None:
    from horizon_trader.execution import alpaca_book as ab

    clock = clock or Clock()
    today = clock.now().date()
    if api is None:
        from horizon_trader.execution.alpaca_broker import AlpacaPaper

        api = AlpacaPaper(PREFIX)
    got, why = setup(api, today)
    ledger = Ledger.load(LEDGER, STARTING_CASH, root)
    if got is None:
        log.warning(why)
        append_event(Ledger.directory(LEDGER, root) / "checks.jsonl", clock, "skip", reason=why)
        return
    plan, open_ts = got
    broker = ab.AlpacaBookBroker(api, ledger, LIMITS)  # pins the account, kill switch, caps
    log.info("Alpaca paper account %s, ledger %r; sigma from %s", broker.account, ledger.name,
             plan.history_end)  # fmt: skip
    feeds = feeds if feeds is not None else [IBKRBars(), AlpacaBars(api)]
    runner = Runner(api, feeds, ledger, plan, open_ts, clock, broker)
    runner.recover()
    ab.reconcile(api, ledger)
    runner.run()
    ab.reconcile(api, ledger)
    equity = ledger.record_equity(plan.day, {TICKER: plan.prev_close} if ledger.holdings else {})
    log.info(f"{ledger.name}: equity ${equity:,.2f}")


def check_now(api=None) -> dict:
    """Today's plan and the signal on the latest finished bar. Sends nothing."""
    if api is None:
        from horizon_trader.execution.alpaca_broker import AlpacaPaper

        api = AlpacaPaper(PREFIX)
    now = pd.Timestamp.now(tz=NY)
    got, why = setup(api, now.date())
    if got is None:
        print(why)
        return {}
    plan, open_ts = got
    print(f"plan {plan.day}: prev close {plan.prev_close:.2f}, 14d vol {plan.vol:.2%}, "
          f"leverage {plan.leverage():.2f}x, sigma at 10:00 {plan.sigma.get(29, np.nan):.3%}, "
          f"15:30 {plan.sigma.get(359, np.nan):.3%}; history to {plan.history_end}")  # fmt: skip
    out = {}
    for feed in (IBKRBars(), AlpacaBars(api)):
        try:
            live = feed.bars(open_ts, now)
        except Exception as exc:  # noqa: BLE001
            print(f"{feed.name}: {exc!r}")
            continue
        if live.empty:
            print(f"{feed.name}: no bars")
            continue
        done = [j for j in plan.checks if j <= live.index[-1]]
        if not done:
            print(f"{feed.name}: {len(live)} bars, no check passed yet")
            continue
        sig = signal(live, done[-1], plan)
        qty = plan.shares(STARTING_CASH, sig["open"])
        print(f"{feed.name}: {len(live)} bars; check {hhmm(done[-1])}: open {sig['open']:.2f}, "
              f"price {sig['price']:.2f}, band [{sig['lower']:.2f}, {sig['upper']:.2f}], "
              f"vwap {sig['vwap']:.2f} -> target {sig['target']:+d}, {qty} shares")  # fmt: skip
        out[feed.name] = sig
    return out


def status(root=None) -> None:
    ledger = Ledger.load(LEDGER, STARTING_CASH, root)
    folder = Ledger.directory(LEDGER, root)
    print(f"{LEDGER}: cash ${ledger.cash:,.2f}, position {ledger.holdings or 'flat'}")
    if (folder / "equity.csv").exists():
        print(pd.read_csv(folder / "equity.csv").tail(5).to_string(index=False))
    if (folder / "checks.jsonl").exists():
        for line in (folder / "checks.jsonl").read_text(encoding="utf-8").splitlines()[-14:]:
            row = json.loads(line)
            keep = ("at", "price", "target", "position", "source", "error", "reason")
            print(row["time"][:19], row["kind"], {k: row[k] for k in keep if k in row})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("action", choices=("run", "check", "status"))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.action == "status":
        status()
    elif args.action == "check":
        check_now()
    else:
        from horizon_trader.config import require_ops

        require_ops("run the QQQ noise book")
        try:
            run()
        except GuardError as e:
            raise SystemExit(f"STOPPED: {e}") from None


if __name__ == "__main__":
    main()
