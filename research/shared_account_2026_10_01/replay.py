"""Frozen event replay, four capital levels, controls and declared stresses.

Run prepare.py raw/minutes first. Offline after that. Results do not certify
broker-specific margin, short availability or stop-limit queue fills.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from horizon_trader.backtest.research_stats import risk_free, slice_period
from horizon_trader.backtest.run import target_histories
from horizon_trader.backtest.shared_account import SharedAccount
from horizon_trader.config import data_dir, load_settings
from horizon_trader.execution.costs import IBKR_PLANS
from horizon_trader.intraday import market_momentum as mm
from horizon_trader.intraday.slippage import exit_from

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
DATA = data_dir() / "shared_account_2026_10_01"
RESULTS = HERE / "results"
SETTINGS = ROOT / "research/portfolio_data_review_2026_10_01/results/effective_daily_settings.json"
SAVED_ORB = (
    data_dir() / "results/20260925-031640_orb-top1-1atr-stop-limit-0c-5k-fixed/trades.parquet"
)
SIZES = (5000, 10000, 15000, 20000)
WEIGHTS = {
    "frozen": (0.515977585263584, 0.20332137002741696, 0.2807010447089991),
    "reduced": (1.0, 0.25, 0.5),
    "core": (1.0, 0.0, 0.0),
    "orb": (0.0, 1.0, 0.0),
    "noise": (0.0, 0.0, 1.0),
    "without_core": (0.0, 0.25, 0.5),
    "without_orb": (1.0, 0.0, 0.5),
    "without_noise": (1.0, 0.25, 0.0),
    "qqq_buy_hold": (0.0, 0.0, 0.0),
    "qqq_vol_only": (0.0, 0.0, 0.0),
}


@dataclass(frozen=True)
class Scenario:
    name: str = "base"
    cap: float = 2.0
    short: bool = True
    plan: str = "fixed"
    daily_bps: float = 5.0
    extra_cent: float = 0.0
    intraday_delay: int = 0
    daily_delay: int = 1
    miss_mod: int = 0
    withholding: float = 0.0
    minimum_fee: float | None = None


SCENARIOS = [
    Scenario(),
    Scenario("tiered", plan="tiered"),
    Scenario("higher_cost", daily_bps=10.0, extra_cent=0.01),
    Scenario("delay_1m", intraday_delay=1),
    Scenario("delay_5m", intraday_delay=5),
    Scenario("daily_delay", daily_delay=2),
    Scenario("no_shorts", short=False),
    Scenario("unlevered_long_only", cap=1.0, short=False),
    Scenario("hypothetical_4x", cap=4.0),
    Scenario("missed_orb", miss_mod=5),
    Scenario("withholding_30pct", withholding=0.30),
    Scenario("no_minimum_diagnostic", minimum_fee=0.0),
    Scenario(
        "joint",
        cap=1.0,
        short=False,
        daily_bps=10.0,
        extra_cent=0.01,
        intraday_delay=5,
        daily_delay=2,
        miss_mod=5,
        withholding=0.30,
    ),
]


def historical_raw(frame):
    splits = frame["Stock Splits"].replace(0, 1)
    future_factor = splits.iloc[::-1].cumprod().iloc[::-1] / splits
    result = frame[["Open", "Close", "Dividends"]].mul(future_factor, axis=0)
    result.columns = ["open", "close", "dividend"]
    result["split"] = splits
    return result


class Inputs:
    def __init__(self):
        self.settings = load_settings(SETTINGS)
        self.symbols = self.settings.universe
        frames = {s: pd.read_parquet(data_dir() / "bars" / f"{s}.parquet") for s in self.symbols}
        self.adjusted = pd.DataFrame({s: f.close for s, f in frames.items()}).sort_index()
        self.targets = target_histories(self.settings, self.adjusted)["combined"]
        self.raw = {
            s: historical_raw(pd.read_parquet(DATA / "raw" / f"{s}.parquet")) for s in self.symbols
        }
        for symbol, frame in self.raw.items():
            path = DATA / "dividend_dates" / f"{symbol}.json"
            dates = {
                pd.Timestamp(r["ex_dividend_date"]): pd.Timestamp(r["pay_date"])
                for r in json.loads(path.read_text())
                if r.get("pay_date")
            }
            frame["pay_date"] = [dates.get(d, d + pd.Timedelta(days=45)) for d in frame.index]
            frame["pay_date_source"] = [
                "vendor" if d in dates else "45_day_proxy" for d in frame.index
            ]
        self.opens = pd.DataFrame({s: f.open for s, f in self.raw.items()})
        self.closes = pd.DataFrame({s: f.close for s, f in self.raw.items()})
        self.rates = pd.read_parquet(data_dir() / "research_cycle_2026_10_01/inputs/dff.parquet").ff
        self.orb = pd.read_parquet(SAVED_ORB)
        self.orb["date"] = self.orb.entry_time.dt.tz_localize(None).dt.normalize()
        self.orb = self.orb.set_index("date")
        qminute = pd.read_parquet(data_dir() / "massive/derived/minute_QQQ.parquet")
        qdaily = pd.read_parquet(data_dir() / "massive/derived/day_QQQ.parquet")
        self.qbars = mm.make_bars(qminute, qdaily)
        noise = mm.noise_trades(self.qbars)
        self.noise = {d: g for d, g in noise.groupby("date")}
        self.vol = mm.daily_vol(self.qbars.daily)
        self.vol_control = self.adjusted.QQQ.pct_change().rolling(63).std() * np.sqrt(252)
        self.sessions = {}
        self.events = {}
        self.top = pd.read_parquet(data_dir() / "massive/derived/orb5_stop1_trades.parquet")
        self.top = self.top[self.top["rank"].eq(1)].set_index("date")
        self.audit = []

    def session(self, day):
        if day in self.sessions:
            return self.sessions[day]
        frame = pd.read_parquet(DATA / "sessions" / f"{day:%Y-%m-%d}.parquet")
        frame["minute"] = frame.ts.dt.hour * 60 + frame.ts.dt.minute - 570
        length = int(self.qbars.daily.at[day, "session_len"])
        frame = frame[frame.minute.lt(length)]
        opens = frame.pivot(index="minute", columns="ticker", values="open").reindex(range(length))
        closes = frame.pivot(index="minute", columns="ticker", values="close").reindex(
            range(length)
        )
        # Last observed minute CLOSE is available at the NEXT minute, never backfill.
        marks = closes.ffill().shift(1)
        marks.loc[0] = opens.loc[0]
        marks = marks.ffill()
        missing = [s for s in self.symbols if s not in marks or marks[s].isna().any()]
        if missing:
            raise ValueError(f"Missing causal core marks on {day}: {missing}")
        result = dict(frame=frame, marks=marks, opens=opens, closes=closes.ffill(), length=length)
        self.sessions[day] = result
        return result

    def day_events(self, day, delay):
        key = (day, delay)
        if key in self.events:
            return self.events[key]
        session = self.session(day)
        length = session["length"]
        events = {}

        def add(minute, sleeve, target, price, slip, stop_dist=0.0, phase=0):
            events.setdefault((minute, phase), []).append(
                dict(sleeve=sleeve, target=target, price=price, slip=slip, stop_dist=stop_dist)
            )

        if day in self.noise:
            for trade in self.noise[day].itertuples():
                enter = int(trade.entry_idx) + delay
                leave = min(
                    int(trade.exit_idx) + (delay if trade.exit_reason != "close" else 0), length
                )
                if enter >= leave or enter >= length:
                    continue
                entry_px = self.qbars.fill.at[day, enter]
                exit_px = (
                    self.qbars.daily.at[day, "close"]
                    if leave == length
                    else self.qbars.fill.at[day, leave]
                )
                if not np.isfinite(entry_px) or not np.isfinite(exit_px):
                    raise ValueError("Missing QQQ execution price")
                add(enter, "noise", trade.side, entry_px, 0.005)
                add(leave, "noise", 0, exit_px, 0.0 if leave == length else 0.005)
        if day in self.orb.index or (delay and day in self.top.index):
            if delay:
                candidate = self.top.loc[day]
                # Place the unchanged stop-limit at 09:35 + latency, then require
                # a trigger and a later-minute trade-through. Selection uses all
                # candidates, never whether a baseline order happened to fill.
                bars = session["frame"]
                bars = bars[bars.ticker.eq(candidate.ticker) & bars.minute.ge(5 + delay)]
                bars = bars.sort_values("minute").reset_index(drop=True)
                hit = (
                    bars.high.ge(candidate.level)
                    if candidate.side > 0
                    else bars.low.le(candidate.level)
                )
                if not hit.any():
                    self.events[key] = events
                    return events
                trigger = int(np.flatnonzero(hit.to_numpy())[0])
                through = (
                    bars.low.le(candidate.level - 0.01)
                    if candidate.side > 0
                    else bars.high.ge(candidate.level + 0.01)
                )
                through.iloc[: trigger + 1] = False
                if not through.any():
                    self.events[key] = events
                    return events
                j = int(np.flatnonzero(through.to_numpy())[0])
                stamp = day + pd.Timedelta(minutes=570 + int(bars.minute.iloc[j]))
                trade = SimpleNamespace(
                    symbol=candidate.ticker,
                    side=candidate.side,
                    atr=candidate.atr,
                    entry_px=candidate.level,
                    exit_px=candidate.close,
                    entry_time=stamp,
                    exit_time=day + pd.Timedelta(minutes=570 + length),
                )
            else:
                trade = self.orb.loc[day]
            enter = trade.entry_time.hour * 60 + trade.entry_time.minute - 570
            leave = trade.exit_time.hour * 60 + trade.exit_time.minute - 570
            leave = min(leave, length)
            entry_px, exit_px = trade.entry_px, trade.exit_px
            entry_slip, exit_slip = 0.0, 0.0  # saved prices already include measured exit slip
            # The measured baseline is reused exactly; delayed orders above use
            # their own trigger and fill. Re-evaluate the stop after the new fill.
            if delay:
                enter = int(bars.minute.iloc[j])
                exit_px, stopped, k = exit_from(
                    bars.open.to_numpy(),
                    bars.high.to_numpy(),
                    bars.low.to_numpy(),
                    j,
                    entry_px,
                    int(trade.side),
                    float(trade.atr),
                    float(self.top.loc[day, "close"]),
                )
                leave = int(bars.minute.iloc[k]) if stopped else length
                exit_slip = (
                    0.05 if stopped else 0.0
                )  # prespecified conservative delayed-stop assumption
            add(
                enter,
                "orb",
                (trade.symbol, int(trade.side)),
                entry_px,
                entry_slip,
                float(trade.atr),
            )
            add(
                leave,
                "orb",
                (trade.symbol, 0),
                exit_px,
                exit_slip,
                phase=1 if leave == enter else 0,
            )
        self.events[key] = events
        return events


def replay(inputs, name, capital, scenario, start="2021-11-01", end="2026-09-24", daily_only=False):
    index = inputs.closes.loc[start:end].dropna().index
    if len(index) < 2:
        raise ValueError("too few sessions")
    costs = IBKR_PLANS[scenario.plan]
    if scenario.minimum_fee is not None:
        costs = replace(costs, min_per_order=scenario.minimum_fee)
    account = SharedAccount(float(capital), costs, scenario.cap, scenario.short)
    cw, ow, nw = WEIGHTS[name]
    rows = [
        dict(
            date=index[0],
            equity=capital,
            cash=capital,
            receivables=0.0,
            gross=0.0,
            peak_gross=0.0,
            minute_min_equity=capital,
            fees=0.0,
            slippage=0.0,
            orders=0,
            rejected=0,
            funding=0.0,
            borrow=0.0,
            breach=False,
            turnover=0.0,
        )
    ]
    rates = inputs.rates.reindex(index, method="ffill")
    previous_nav = float(capital)
    for number, day in enumerate(index[1:], 1):
        previous = index[number - 1]
        before_orders, before_decisions = len(account.orders), len(account.decisions)
        financing = (
            max(-account.cash, 0)
            * max(rates.iloc[number - 1] + 0.015, 0)
            * (day - previous).days
            / 360
        )
        account.cash -= financing
        if financing:
            account.flows.append(dict(date=day, kind="funding", amount=-financing))
        for symbol, raw in inputs.raw.items():
            action = raw.loc[day]
            if action["split"] != 1:
                account.split(symbol, action["split"])
            if action.dividend:
                account.dividend(
                    day, symbol, action.dividend, action.pay_date, scenario.withholding
                )
        account.settle(day)
        marks = inputs.opens.loc[day].to_dict()
        starting_nav = account.equity(marks)
        if starting_nav <= 0:
            raise RuntimeError("account insolvent")
        session = None if daily_only else inputs.session(day)
        length = 390 if daily_only else session["length"]
        decisions = {}
        signal_pos = inputs.targets.index.get_loc(day) - scenario.daily_delay
        signal_day = inputs.targets.index[signal_pos]
        close_prices = inputs.closes.loc[previous]
        if name == "qqq_buy_hold":
            if number == 1:
                decisions = {"core": {"QQQ": int(0.99 * previous_nav / close_prices.QQQ)}}
        elif name == "qqq_vol_only":
            weight = min(1.5, 0.2 / inputs.vol_control.loc[signal_day])
            target = int(0.99 * previous_nav * weight / close_prices.QQQ)
            held = account.sleeves.get("core", {}).get("QQQ", 0)
            if abs(target - held) * close_prices.QQQ >= 0.02 * previous_nav:
                decisions = {"core": {"QQQ": target}}
        elif cw:
            targets = inputs.targets.loc[signal_day]
            actual = account.sleeves.get("core", {})
            updates = {}
            for symbol in inputs.symbols:
                target = int(
                    0.99 * previous_nav * cw * targets.get(symbol, 0) / close_prices[symbol]
                )
                difference = target - actual.get(symbol, 0)
                if difference and (
                    target == 0
                    or abs(difference) * close_prices[symbol] >= max(25.0, 0.02 * previous_nav)
                ):
                    updates[symbol] = target
            decisions = {"core": updates}
        account.rebalance(
            decisions,
            marks,
            day + pd.Timedelta(hours=9.5),
            slips={s: p * scenario.daily_bps / 10000 for s, p in marks.items()},
            reason="daily_prior_close",
        )
        peak_gross = account.gross(marks) / account.equity(marks)
        min_nav = account.equity(marks)
        breach = peak_gross > scenario.cap + 1e-8
        last_minute = 0
        max_short_notional = 0.0

        def mark_interval(until, session=session, day=day):
            nonlocal peak_gross, min_nav, breach, last_minute, max_short_notional
            if daily_only or until <= last_minute:
                return
            holdings = account.positions()
            if holdings:
                path = session["closes"].iloc[last_minute:until].reindex(columns=list(holdings))
                if path.isna().any().any():
                    raise ValueError(f"Unpriced held position on {day}")
                values = path.to_numpy() * np.array(list(holdings.values()))
                nav = account.cash + sum(a for _, a in account.receivables) + values.sum(axis=1)
                gross = np.abs(values).sum(axis=1) / nav
                peak_gross = max(peak_gross, float(gross.max()))
                min_nav = min(min_nav, float(nav.min()))
                breach |= bool((gross > scenario.cap + 1e-8).any())
                max_short_notional = max(
                    max_short_notional, float((-np.minimum(values, 0).sum(axis=1)).max())
                )
            last_minute = until

        events = (
            {} if daily_only or not (ow or nw) else inputs.day_events(day, scenario.intraday_delay)
        )
        events = {
            key: [e for e in es if (e["sleeve"] == "orb" and ow) or (e["sleeve"] == "noise" and nw)]
            for key, es in events.items()
        }
        reserved_quantity = 0
        if ow and day in inputs.top.index:
            events[(5, -1)] = [{"sleeve": "reserve"}]
            events[(length, 2)] = [{"sleeve": "cancel_reservation"}]
        missed = scenario.miss_mod and int(day.strftime("%Y%m%d")) % scenario.miss_mod == 0
        noise_qty = (
            int(starting_nav * nw * min(4.0, 0.02 / inputs.vol.loc[day]) / marks["QQQ"])
            if nw
            else 0
        )
        for (minute, _phase), group in sorted(events.items()):
            if not group:
                continue
            mark_interval(minute)
            marks = (
                inputs.closes.loc[day].to_dict()
                if minute == length
                else session["marks"].loc[minute].dropna().to_dict()
            )
            if group[0]["sleeve"] in {"reserve", "cancel_reservation"}:
                if group[0]["sleeve"] == "reserve":
                    candidate = inputs.top.loc[day]
                    wanted = int(
                        min(
                            0.01 * starting_nav * ow / candidate.stop_dist,
                            4 * starting_nav * ow / candidate.level,
                        )
                    )
                    available = max(
                        0.0,
                        scenario.cap
                        * (account.equity(marks) - sum(a for _, a in account.receivables))
                        - account.gross(marks),
                    )
                    reserved_quantity = min(wanted, int(available / candidate.level))
                    if not scenario.short and candidate.side < 0:
                        reserved_quantity = 0
                    account.reserved_gross = reserved_quantity * candidate.level
                    account.decisions.append(
                        dict(
                            time=day + pd.Timedelta(minutes=575),
                            symbol=candidate.ticker,
                            requested=wanted,
                            filled=0,
                            unfilled=wanted - reserved_quantity,
                            reason="reserve_orb",
                            equity=account.equity(marks),
                            gross=account.gross(marks),
                            cash=account.cash,
                            reserved_gross=account.reserved_gross,
                            force=False,
                        )
                    )
                else:
                    account.reserved_gross = 0.0
                continue
            intents, slips = {}, {}
            # An exit followed by entry at the same instant becomes one net reversal.
            for event in sorted(
                group, key=lambda e: bool(e["target"] if e["sleeve"] == "noise" else e["target"][1])
            ):
                sleeve = event["sleeve"]
                if sleeve == "noise":
                    symbol, side = "QQQ", event["target"]
                    target = side * noise_qty
                else:
                    symbol, side = event["target"]
                    target = (
                        int(
                            min(
                                0.01 * starting_nav * ow / event["stop_dist"],
                                4 * starting_nav * ow / event["price"],
                            )
                        )
                        * side
                        if side
                        else 0
                    )
                    if missed and side:
                        account.decisions.append(
                            dict(
                                time=day + pd.Timedelta(minutes=570 + minute),
                                symbol=symbol,
                                requested=target,
                                filled=0,
                                unfilled=target,
                                reason="missed_orb_stress",
                                equity=account.equity(marks),
                                gross=account.gross(marks),
                                cash=account.cash,
                                force=False,
                            )
                        )
                        continue
                    if side:
                        target = int(side) * min(abs(target), reserved_quantity)
                        account.reserved_gross = 0.0
                marks[symbol] = event["price"]
                intents.setdefault(sleeve, {})[symbol] = target
                slips[symbol] = event["slip"] + scenario.extra_cent
            account.rebalance(
                intents,
                marks,
                day + pd.Timedelta(minutes=570 + minute),
                slips=slips,
                reason="intraday",
            )
            peak_gross = max(peak_gross, account.gross(marks) / account.equity(marks))
            breach |= account.gross(marks) > scenario.cap * account.equity(marks) + 1e-8
            min_nav = min(min_nav, account.equity(marks))
            max_short_notional = max(
                max_short_notional,
                sum(-q * marks[s] for s, q in account.positions().items() if q < 0),
            )
        mark_interval(length)
        account.reserved_gross = 0.0
        marks = inputs.closes.loc[day].to_dict()
        # Force intraday inventory flat as a combined closing batch. Partial exits
        # from prior buying-power constraints cannot silently survive overnight.
        flatten = {
            sleeve: {s: 0 for s in account.sleeves.get(sleeve, {})} for sleeve in ("orb", "noise")
        }
        for symbol in account.positions():
            if symbol not in marks:
                marks[symbol] = float(inputs.top.loc[day, "close"])
        account.rebalance(
            flatten,
            marks,
            day + pd.Timedelta(minutes=570 + length),
            slips={s: scenario.extra_cent for s in marks},
            reason="session_flat",
            force=True,
        )
        borrow = max_short_notional * 0.03 / 360
        account.cash -= borrow
        if borrow:
            account.flows.append(dict(date=day, kind="short_fee_assumption", amount=-borrow))
        nav = account.equity(marks)
        gross = account.gross(marks) / nav
        # Volatility control explicitly permits its frozen 1.5x overnight target.
        overnight_cap = 2.0 if name == "qqq_vol_only" else 1.0
        breach |= gross > overnight_cap + 1e-8
        fills = account.orders[before_orders:]
        intents = account.decisions[before_decisions:]
        rows.append(
            dict(
                date=day,
                equity=nav,
                cash=account.cash,
                receivables=sum(a for _, a in account.receivables),
                gross=gross,
                peak_gross=peak_gross,
                minute_min_equity=min(min_nav, nav),
                fees=sum(r["fee"] for r in fills),
                slippage=sum(r["slippage"] for r in fills),
                orders=len(fills),
                rejected=sum(bool(r["unfilled"]) for r in intents),
                funding=financing,
                borrow=borrow,
                breach=breach,
                turnover=sum(abs(r["quantity"] * r["reference"]) for r in fills) / starting_nav,
            )
        )
        identity = (
            account.cash
            + sum(q * marks[s] for s, q in account.positions().items())
            + sum(a for _, a in account.receivables)
        )
        if not np.isclose(nav, identity) or not np.isfinite(nav) or nav <= 0:
            raise RuntimeError("cash + holdings + receivables identity failed")
        previous_nav = nav
    return pd.DataFrame(rows).set_index("date"), account


def stats(frame, rates):
    equity = frame.equity
    returns = equity.pct_change().iloc[1:]
    excess = returns - risk_free(equity.index, rates).iloc[1:]
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    counted = frame.iloc[1:]
    return dict(
        cagr=(equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1,
        max_drawdown=(equity / equity.cummax() - 1).min(),
        sharpe=excess.mean() / excess.std() * np.sqrt(252) if excess.std() else np.nan,
        final_equity=equity.iloc[-1],
        fees=counted.fees.sum(),
        orders=counted.orders.sum(),
        clipped_or_rejected=counted.rejected.sum(),
        peak_gross=counted.peak_gross.max(),
        breach_days=counted.breach.sum(),
        funding=counted.funding.sum(),
        borrow=counted.borrow.sum(),
        turnover_annual=counted.turnover.sum() / years,
    )


def benchmark(inputs, index, capital):
    # Enter at the same first OPEN as the account; subsequent gross dividend reinvestment.
    q = pd.read_parquet(DATA / "raw/QQQ.parquet")
    adjusted_open = q.Open * q["Adj Close"] / q.Close
    equity = capital * q["Adj Close"].reindex(index) / adjusted_open.loc[index[1]]
    equity.iloc[0] = capital
    result = pd.DataFrame({"equity": equity}, index=index)
    for column in [
        "fees",
        "orders",
        "rejected",
        "peak_gross",
        "breach",
        "funding",
        "borrow",
        "turnover",
    ]:
        result[column] = 0.0
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="plumbing only: first month, $5k")
    parser.add_argument("--stage", choices=["main", "stress", "older"], default="main")
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    inputs = Inputs()
    sources = [
        Path(__file__),
        HERE / "protocol.md",
        SETTINGS,
        SAVED_ORB,
        ROOT / "src/horizon_trader/backtest/shared_account.py",
        ROOT / "src/horizon_trader/execution/costs.py",
        ROOT / "src/horizon_trader/backtest/run.py",
    ]
    sources += sorted((DATA / "raw").glob("*.parquet"))
    sources += sorted((DATA / "dividend_dates").glob("*.json"))
    sources += sorted((DATA / "sessions").glob("*.parquet"))
    sources += [data_dir() / "bars" / f"{s}.parquet" for s in inputs.symbols]
    sources += [
        data_dir() / "massive/derived" / name
        for name in ("minute_QQQ.parquet", "day_QQQ.parquet", "orb5_stop1_trades.parquet")
    ]
    sources += [data_dir() / "research_cycle_2026_10_01/inputs/dff.parquet"]
    source_hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
    }
    rows = []
    end = "2021-12-01" if args.quick else "2026-09-24"
    sizes = (5000,) if args.quick else SIZES
    scenarios = SCENARIOS[:1] if args.stage != "stress" else SCENARIOS[1:]
    names = list(WEIGHTS) if args.stage == "main" else ["frozen", "reduced"]
    starts = [("continuous", "2021-11-01")]
    if args.stage == "main" and not args.quick:
        starts.append(("restart_2024", "2023-12-29"))
    if args.stage == "older":
        names, starts = ["core", "qqq_buy_hold", "qqq_vol_only"], [("older_daily", "2007-01-03")]
        end = "2021-10-01"
    for restart, start in starts:
        for scenario in scenarios:
            for capital in sizes:
                for name in names:
                    label = f"{restart}_{scenario.name}_{name}_{capital}"
                    if args.quick:
                        label += "_quick"
                    daily, account = replay(
                        inputs,
                        name,
                        capital,
                        scenario,
                        start,
                        end,
                        daily_only=args.stage == "older",
                    )
                    ref = benchmark(inputs, daily.index, capital)
                    bundle = DATA / "runs" / label
                    bundle.mkdir(parents=True, exist_ok=True)
                    daily.to_parquet(bundle / "daily.parquet")
                    pd.DataFrame(account.orders).to_parquet(bundle / "orders.parquet")
                    pd.DataFrame(account.decisions).to_parquet(bundle / "decisions.parquet")
                    pd.DataFrame(account.flows).to_parquet(bundle / "flows.parquet")
                    periods = [
                        ("full", start, end),
                        ("reused_2024_plus", "2024-01-01", end),
                        ("inflation_2022", "2022-01-01", "2022-12-31"),
                    ]
                    if args.stage == "older":
                        periods = [
                            ("older_full", start, end),
                            ("gfc", "2007-01-03", "2009-12-31"),
                            ("pre_covid", "2010-01-01", "2019-12-31"),
                            ("covid", "2020-01-01", "2020-12-31"),
                        ]
                    for period, begin, finish in periods:
                        if daily.loc[begin:finish].empty:
                            continue
                        d, b = slice_period(daily, begin, finish), slice_period(ref, begin, finish)
                        if len(d) < 3:
                            continue
                        result, control = stats(d, inputs.rates), stats(b, inputs.rates)
                        passed = (
                            result["cagr"] > control["cagr"]
                            and abs(result["max_drawdown"]) <= 0.9 * abs(control["max_drawdown"])
                            and result["breach_days"] == 0
                        )
                        rows.append(
                            dict(
                                restart=restart,
                                scenario=scenario.name,
                                capital=capital,
                                strategy=name,
                                period=period,
                                start=str(d.index[0].date()),
                                end=str(d.index[-1].date()),
                                **result,
                                qqq_cagr=control["cagr"],
                                qqq_max_drawdown=control["max_drawdown"],
                                passes=passed,
                            )
                        )
                    print(
                        f"{label}: NAV {daily.equity.iloc[-1]:,.2f}; {len(account.orders)} orders; "
                        f"{int(daily.breach.sum())} breach days",
                        flush=True,
                    )
                pd.DataFrame(rows).to_csv(
                    RESULTS / f"{args.stage}_metrics{'_quick' if args.quick else ''}.csv",
                    index=False,
                )
    manifest = {
        "protocol_sha256": hashlib.sha256((HERE / "protocol.md").read_bytes()).hexdigest(),
        "sizes": list(sizes),
        "stage": args.stage,
        "quick": args.quick,
        "python": sys.version,
        "source_hashes": source_hashes,
    }
    suffix = "_quick" if args.quick else ""
    (RESULTS / f"{args.stage}_manifest{suffix}.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
