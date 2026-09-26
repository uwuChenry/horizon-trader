"""Opening Range Breakout on Stocks in Play (Zarattini, Barbon & Aziz 2024, SSRN 4729284).

    uv run python -m horizon_trader.intraday.orb [--rebuild] [--minutes 5]

Paper rules (defaults, not tuned), applied to every US common stock incl. delisted ones:
  filters  open > $5, 14-day avg volume >= 1M shares, 14-day ATR > $0.50
  select   relative volume of the first n minutes >= 1, top 20 by relative volume
  side     long if the n-minute candle closed up, short if down, skip if flat
  entry    stop order at the opening-range high (long) / low (short)
  stop     10% of ATR from the entry fill; otherwise exit at the close
  sizing   1% of equity lost if stopped, at most 4x leverage (split evenly across the top N)

Simulation choices the paper doesn't spell out:
  - Minute bars can't say whether the entry or the stop came first inside the entry minute,
    and with a stop of 0.1 ATR (median 14 cents) that decides the result: about half of all
    trades touch the stop inside the entry minute. Exits are computed three ways (see
    simulate_trade); "path" is the usual OHLC-order guess and the default.
  - A gap through a level fills at the bar's open (entry or stop), not at the level.
  - Close exits fill at the official close (a market-on-close order), without slippage.
    Slippage is charged per share on stop fills (every entry, and stop-outs).
  - Short borrow cost isn't modeled. Shorts under the short-sale restriction (stock down 10%
    from yesterday's close before entry) are flagged and reported separately.
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.backtest.metrics import summarize
from horizon_trader.config import data_dir
from horizon_trader.data import massive, massive_ref
from horizon_trader.execution.costs import FINRA_TAF, IBKR_PLANS, SEC_FEE, CostModel
from horizon_trader.intraday import features as F

CLOSE_TIME = pd.Timedelta(hours=6, minutes=30)  # 9:30 + 6h30 = 16:00


@dataclass(frozen=True)
class OrbRules:
    minutes: int = 5
    lookback: int = 14
    min_price: float = 5.0
    min_avg_volume: float = 1_000_000
    min_atr: float = 0.50
    min_relvol: float = 1.0
    stop_atr: float = 0.10
    keep: int = 50  # candidates simulated per day; portfolios take the top N of these
    min_dollar_volume: float = 0.0  # 14-day avg volume x prev close; a large-cap proxy


RULES = OrbRules()


# ---------------------------------------------------------------- selection and simulation


def select_candidates(day: pd.DataFrame, rules: OrbRules = RULES) -> pd.DataFrame:
    """Rank one day's tickers (index) by relative volume after the paper's filters.

    `day` needs columns open, atr, avg_volume, relvol, or_open, or_close, opens_on_time
    (and prev_close when a dollar-volume floor is set). Both avg_volume and prev_close
    come from days before t, so the filter is known at the open.
    """
    ok = (
        day["opens_on_time"].fillna(False).astype(bool)
        & (day["open"] > rules.min_price)
        & (day["avg_volume"] >= rules.min_avg_volume)
        & (day["atr"] > rules.min_atr)
        & (day["relvol"] >= rules.min_relvol)
        & (day["or_close"] != day["or_open"])
    )
    if rules.min_dollar_volume > 0:  # before the top-N cut, or large caps ranked low vanish
        ok &= day["avg_volume"] * day["prev_close"] >= rules.min_dollar_volume
    c = day[ok].sort_index().sort_values("relvol", ascending=False, kind="stable").head(rules.keep)
    c = c.assign(side=np.sign(c["or_close"] - c["or_open"]).astype(int))
    return c.assign(rank=np.arange(1, len(c) + 1))


MODES = ("cons", "path", "opt")


def simulate_trade(
    o: np.ndarray,
    h: np.ndarray,
    low: np.ndarray,
    c: np.ndarray,
    side: int,
    level: float,
    stop_dist: float,
    close_px: float,
) -> dict | None:
    """One stop-entry trade on the bars after the opening range. None if never triggered.

    A minute bar doesn't say whether the stop was touched before or after the entry inside
    the entry minute, so the exit is computed three ways (exit index len(o) = the close):
      cons  any touch of the stop in the entry minute counts (pessimistic)
      path  assume up-bars go open-low-high-close and down-bars open-high-low-close
      opt   the stop is only checked from the next minute. Not an upper bound: a skipped
            stop often gaps through on the next open and loses several R instead of one.
    """
    hits = np.flatnonzero(h >= level) if side > 0 else np.flatnonzero(low <= level)
    if not len(hits):
        return None
    k = int(hits[0])
    fill = max(level, o[k]) if side > 0 else min(level, o[k])
    stop = fill - side * stop_dist
    adverse = low if side > 0 else h

    def breached(x):
        return x <= stop if side > 0 else x >= stop

    later = np.flatnonzero(breached(adverse[k + 1 :]))
    gapped = o[k] >= level if side > 0 else o[k] <= level
    with_trend = c[k] >= o[k] if side > 0 else c[k] <= o[k]
    # path: in a bar moving our way, the adverse extreme came before the level was crossed,
    # so only a close back through the stop counts; otherwise the adverse extreme came after
    in_entry_bar = {
        "cons": bool(breached(adverse[k])),
        "path": bool(breached(c[k]) if with_trend and not gapped else breached(adverse[k])),
        "opt": False,
    }
    out = {"entry_idx": k, "entry_px": fill, "stop_px": stop}
    for mode, stopped_now in in_entry_bar.items():
        if stopped_now:
            px, j = stop, k
        elif len(later):
            j = k + 1 + int(later[0])
            px = min(o[j], stop) if side > 0 else max(o[j], stop)  # a gap fills at the open
        else:
            px, j = close_px, len(o)
        out |= {f"exit_px_{mode}": px, f"exit_idx_{mode}": j, f"stopped_{mode}": j < len(o)}
    return out


def simulate_day(
    session: pd.DataFrame, cands: pd.DataFrame, day: date, rules: OrbRules = RULES
) -> pd.DataFrame:
    """Every candidate's trade (or non-trade) on one day. `session` = that day's 9:30-16:00 bars."""
    start = F.session_open(day)
    after_or = start + pd.Timedelta(minutes=rules.minutes)
    by_ticker = dict(tuple(session.groupby("ticker", sort=False)))
    rows = []
    for tk, c in cands.iterrows():
        bars = by_ticker.get(tk)
        row = {"date": pd.Timestamp(day), "ticker": tk, "triggered": False}
        row |= {k: c[k] for k in ("rank", "relvol", "side", "atr", "open", "prev_close", "close")}
        level = c["or_high"] if c["side"] > 0 else c["or_low"]
        stop_dist = rules.stop_atr * c["atr"]
        row |= {"level": level, "stop_dist": stop_dist}
        if bars is not None:
            post = bars[bars["ts"] >= after_or]
            o, h, lo, cl = (post[f].to_numpy(float) for f in ("open", "high", "low", "close"))
            res = simulate_trade(o, h, lo, cl, int(c["side"]), level, stop_dist, c["close"])
            if res is not None:
                k = res["entry_idx"]
                low_so_far = bars.loc[bars["ts"] <= post["ts"].iloc[k], "low"].min()
                row |= res | {"triggered": True, "entry_time": post["ts"].iloc[k]}
                row["ssr"] = c["side"] < 0 and low_so_far <= 0.9 * c["prev_close"]
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- building the trade table


def _derived_path(name: str, suffix: str = ".parquet") -> Path:
    return data_dir() / "massive" / "derived" / f"{name}{suffix}"


def _derived(name: str) -> pd.DataFrame | None:
    path = _derived_path(name)
    return pd.read_parquet(path) if path.exists() else None


def _save(df: pd.DataFrame, name: str) -> None:
    path = _derived_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)  # atomic: an interrupted save never corrupts the cache


def _done_days(name: str) -> set[date] | None:
    """Days already processed for a cache (including days with nothing to store)."""
    path = _derived_path(name, ".days.json")
    return {date.fromisoformat(d) for d in json.loads(path.read_text())} if path.exists() else None


def _save_done_days(name: str, days: set[date]) -> None:
    _derived_path(name, ".days.json").write_text(json.dumps(sorted(map(str, days))))


def workers(n: int | None = None) -> int:
    """Worker processes for parallel steps: all cores but two, unless told otherwise."""
    return max(1, n if n is not None else (os.cpu_count() or 2) - 2)


def _parallel(fn, jobs: list, n_workers: int | None, label: str) -> list:
    """fn(job) for every job, in worker processes, results in job order. Tiny batches run
    serially, where starting processes would cost more than it saves."""
    n = workers(n_workers)
    if n == 1 or len(jobs) < 8:
        return [fn(j) for j in jobs]
    out = []
    with ProcessPoolExecutor(max_workers=n) as pool:
        chunk = max(1, len(jobs) // (n * 4))
        for i, res in enumerate(pool.map(fn, jobs, chunksize=chunk), 1):
            out.append(res)
            if i % 200 == 0 or i == len(jobs):
                print(f"  {label}: {i}/{len(jobs)} days", flush=True)
    return out


OR_COLS = ["or_open", "or_high", "or_low", "or_close", "or_volume", "opens_on_time"]


def _or_job(job: tuple[date, int]) -> pd.DataFrame:
    d, minutes = job
    start = F.session_open(d)
    window = [("ts", ">=", start), ("ts", "<", start + pd.Timedelta(minutes=minutes))]
    bars = pd.read_parquet(massive.local_path("minute", d), filters=window)
    return F.opening_range(bars, d, minutes).reset_index().assign(date=pd.Timestamp(d))


def opening_ranges(
    days: list[date], tickers: set[str], minutes: int, rebuild: bool = False, n_workers=None
) -> pd.DataFrame:
    """Opening range of every ticker on every day, cached (long format)."""
    name = f"or{minutes}"
    cached = None if rebuild else _derived(name)
    have = set() if cached is None else set(cached["date"].dt.date)
    missing = [d for d in days if d not in have]
    new = _parallel(_or_job, [(d, minutes) for d in missing], n_workers, "opening ranges")
    if new:
        cached = pd.concat([cached, *new] if cached is not None else new, ignore_index=True)
        _save(cached, name)
    return cached[cached["ticker"].isin(tickers) & cached["date"].dt.date.isin(set(days))]


def _session_window(d: date, tickers: list[str]) -> list:
    start = F.session_open(d)
    return [("ticker", "in", tickers), ("ts", ">=", start), ("ts", "<", start + CLOSE_TIME)]


def _simulate_job(job: tuple[date, pd.DataFrame, OrbRules]) -> pd.DataFrame:
    d, cands, rules = job
    window = _session_window(d, list(cands.index))
    session = pd.read_parquet(massive.local_path("minute", d), filters=window)
    return simulate_day(session, cands, d, rules)


def build_trades(rules: OrbRules = RULES, rebuild: bool = False, n_workers=None) -> pd.DataFrame:
    """Candidates and simulated trades for every day with minute data (cached).

    Returns straight from the cache when every day has been processed; otherwise builds the
    daily features and simulates the missing days in parallel worker processes.
    """
    name = f"orb{rules.minutes}_stop{rules.stop_atr:g}_trades"
    if rules.min_dollar_volume > 0:
        name += f"_dv{rules.min_dollar_volume / 1e6:g}M"
    minute_days = massive.local_days("minute")
    day_days = massive.local_days("day")
    days = [d for d in minute_days if d in set(day_days)]
    cached = None if rebuild else _derived(name)
    done = set() if cached is None else (_done_days(name) or set(cached["date"].dt.date))
    todo = [d for d in days if d not in done]
    if not todo:
        return cached.sort_values(["date", "rank"], ignore_index=True)

    common = massive_ref.load_common_tickers()
    panels = F.load_daily_panels(day_days, common)
    splits = massive_ref.load_splits()
    factor = F.split_factors(panels["open"].index, panels["open"].columns, splits)
    feats = F.daily_features(panels, factor, rules.lookback)
    ors = opening_ranges(days, common, rules.minutes, rebuild, n_workers)
    wide = {c: ors.pivot(index="date", columns="ticker", values=c) for c in OR_COLS}
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    traded = panels["volume"].reindex(idx).fillna(0) > 0
    relvol = F.relative_volume(wide["or_volume"], factor.reindex(idx), traded, rules.lookback)

    jobs = []
    for d in todo:  # candidate selection is cheap but needs the big panels: do it here
        t = pd.Timestamp(d)
        day = pd.DataFrame({k: v.loc[t] for k, v in feats.items()})
        day = day.join(pd.DataFrame({k: v.loc[t] for k, v in wide.items()}), how="inner")
        day["relvol"] = relvol.loc[t]
        cands = select_candidates(day, rules)
        if not cands.empty:
            jobs.append((d, cands, rules))
    new = _parallel(_simulate_job, jobs, n_workers, "simulated")
    if new:
        cached = pd.concat([cached, *new] if cached is not None else new, ignore_index=True)
        _save(cached, name)
    _save_done_days(name, done | set(todo))
    return cached.sort_values(["date", "rank"], ignore_index=True)


# ---------------------------------------------------------------- candidate minute bars


def _done_pairs(name: str, cached: pd.DataFrame | None) -> set[tuple[date, str]]:
    """(day, ticker) pairs already fetched for a bar cache (including ones with no bars)."""
    path = _derived_path(name, ".pairs.json")
    if path.exists():
        return {(date.fromisoformat(d), t) for d, t in json.loads(path.read_text())}
    if cached is None:  # older caches tracked days only: rebuild the pair list from the data
        return set()
    pairs = cached[["date", "ticker"]].drop_duplicates()
    return {(d.date(), str(t)) for d, t in zip(pairs["date"], pairs["ticker"], strict=True)}


def _save_done_pairs(name: str, pairs: set[tuple[date, str]]) -> None:
    rows = sorted([str(d), t] for d, t in pairs)
    _derived_path(name, ".pairs.json").write_text(json.dumps(rows))


def _cand_bars_job(job: tuple[date, list[str]]) -> pd.DataFrame:
    d, tickers = job
    bars = pd.read_parquet(massive.local_path("minute", d), filters=_session_window(d, tickers))
    return bars.assign(date=pd.Timestamp(d))


class CandidateBars:
    """Every candidate's 9:30-16:00 minute bars, from one cached file (about 1 GB in memory).

    Built once from the minute files for the tickers in the trade table. Candidate selection
    doesn't depend on the stop width, so one cache serves every stop. A (day, ticker) lookup
    is a dictionary hit instead of decoding a 1.5M-row day file.
    """

    COLS = ["date", "ticker", "ts", "open", "high", "low", "close", "volume"]
    PRICES = ("open", "high", "low", "close", "volume")

    def __init__(self, trades: pd.DataFrame, minutes: int = RULES.minutes, n_workers=None):
        name = f"cand_bars_or{minutes}"
        cached = _derived(name)
        done = _done_pairs(name, cached)
        wanted = {(d.date(), tk) for d, tk in zip(trades["date"], trades["ticker"], strict=True)}
        missing: dict[date, list[str]] = {}
        for d, tk in sorted(wanted - done):  # per (day, ticker): a new filter adds new tickers
            missing.setdefault(d, []).append(tk)
        jobs = sorted(missing.items())
        new = _parallel(_cand_bars_job, jobs, n_workers, "candidate bars")
        if new:
            new = pd.concat(new, ignore_index=True)[self.COLS]
            cached = new if cached is None else pd.concat([cached, new], ignore_index=True)
            _save(cached, name)
        if jobs or not _derived_path(name, ".pairs.json").exists():
            _save_done_pairs(name, done | {(d, tk) for d, tks in jobs for tk in tks})
        df = cached.sort_values(["date", "ticker", "ts"], ignore_index=True)
        self.minutes = minutes
        self._ts = df["ts"].dt.tz_convert(massive.TZ)
        self._cols = {c: df[c].to_numpy(float) for c in self.PRICES}
        day_ns = df["date"].to_numpy().astype("datetime64[ns]").astype("int64")
        tick = df["ticker"].astype(str).to_numpy()
        change = np.r_[True, (day_ns[1:] != day_ns[:-1]) | (tick[1:] != tick[:-1])]
        starts = np.flatnonzero(change)
        ends = np.r_[starts[1:], len(df)]
        self._slices = {
            (int(day_ns[a]), tick[a]): (a, b) for a, b in zip(starts, ends, strict=True)
        }

    def session(self, day: pd.Timestamp, ticker: str) -> pd.DataFrame:
        """That day's 9:30-16:00 bars for the ticker, sorted by time (empty if unknown)."""
        a, b = self._slices.get((pd.Timestamp(day).value, ticker), (0, 0))
        out = pd.DataFrame({c: v[a:b] for c, v in self._cols.items()})
        out.insert(0, "ts", self._ts.iloc[a:b].reset_index(drop=True))
        return out

    def after_or(self, day: pd.Timestamp, ticker: str) -> pd.DataFrame:
        """Bars from the end of the opening range to the close: what the simulators index."""
        s = self.session(day, ticker)
        cut = F.session_open(pd.Timestamp(day).date()) + pd.Timedelta(minutes=self.minutes)
        return s[s["ts"] >= cut].reset_index(drop=True)


# ---------------------------------------------------------------- portfolio accounting

PLANS: dict[str, CostModel] = {
    "none": CostModel(per_share=0.0, min_per_order=0.0),
    "paper": CostModel(per_share=0.0035, min_per_order=0.0),  # what the paper charged
    "paper_2023": CostModel(per_share=0.0005, min_per_order=0.0),  # QQQ ORB paper (2023)
    **IBKR_PLANS,  # fixed / tiered, incl. pass-through and regulatory fees (execution/costs.py)
}
LITE = CostModel(per_share=0.0, min_per_order=0.0, sec_fee_rate=SEC_FEE, taf_per_share=FINRA_TAF)


@dataclass(frozen=True)
class Account:
    equity: float = 25_000.0
    top_n: int = 20
    risk: float = 0.01
    leverage: float = 4.0
    plan: str = "paper"
    slippage: float | None = (
        0.0  # $/share on every stop fill; None = per-trade entry_slip/exit_slip
    )
    same_bar: str = "path"


def trade_costs(qty, entry, exit_, side, plan: str, at_close=None) -> np.ndarray:
    """All-in cost (commission + pass-through + regulatory fees) of the entry and exit orders.

    Vectorized version of CostModel.total() for a round trip (a test keeps the two equal).
    "lite" (IBKR Lite, US residents only): $0 commission during regular hours, but close-auction
    (MOC) exits are only free while auction volume stays under 10% of the month's shares. ORB
    exits most trades at the close, so those pay the lesser of $0.005/share or 1% of value.
    """
    m = LITE if plan == "lite" else PLANS[plan]
    q, entry, exit_ = (
        np.abs(np.asarray(qty, float)),
        np.asarray(entry, float),
        np.asarray(exit_, float),
    )

    def commission(px):
        return np.minimum(np.maximum(m.min_per_order, q * m.per_share), m.max_pct_of_value * q * px)

    sell_px = np.where(np.asarray(side) > 0, exit_, entry)  # long sells at the exit, short at entry
    cost = commission(entry) + commission(exit_) + 2 * q * m.pass_through_per_share
    cost = cost + q * sell_px * m.sec_fee_rate + q * m.taf_per_share
    if plan == "lite":
        at_close = np.ones(len(q), bool) if at_close is None else np.asarray(at_close, bool)
        cost = cost + np.where(at_close, np.minimum(0.005 * q, 0.01 * q * exit_), 0.0)
    return cost


def run_portfolio(
    trades: pd.DataFrame, acct: Account, calendar: pd.DatetimeIndex | None = None
) -> tuple[pd.Series, pd.DataFrame]:
    """Daily equity curve and per-trade fills. Positions are sized on start-of-day equity.

    `calendar` = every trading day of the test. Pass it whenever `trades` holds only the days
    that traded (e.g. filtered to triggered trades): a missing flat day would drop out of the
    equity curve and distort Sharpe and volatility.
    """
    days = calendar if calendar is not None else pd.DatetimeIndex(sorted(trades["date"].unique()))
    live = trades[(trades["rank"] <= acct.top_n) & trades["triggered"]]
    live = live.sort_values("date", kind="stable")  # same within-day order as a groupby
    m = acct.same_bar
    side = live["side"].to_numpy()
    if acct.slippage is None:  # measured, per trade
        slip_in, slip_out = live["entry_slip"].to_numpy(), live["exit_slip"].to_numpy()
    else:
        slip_in = slip_out = np.full(len(live), float(acct.slippage))
    stopped = live[f"stopped_{m}"].to_numpy(bool)
    entry = live["entry_px"].to_numpy(float) + side * slip_in
    exit_ = live[f"exit_px_{m}"].to_numpy(float) - side * slip_out * stopped
    stop_dist = live["stop_dist"].to_numpy(float)
    dates = live["date"].to_numpy()
    starts = (
        np.flatnonzero(np.r_[True, dates[1:] != dates[:-1]]) if len(live) else np.array([], int)
    )
    ends = np.r_[starts[1:], len(live)]
    by_day = {pd.Timestamp(dates[a]): (a, b) for a, b in zip(starts, ends, strict=True)}

    equity, curve = acct.equity, []
    idx, cols = [], {k: [] for k in ("qty", "pnl", "costs", "gross")}
    for d in days:
        span = by_day.get(d)
        if span is not None and equity > 0:
            a, b = span
            s, e, x = side[a:b], entry[a:b], exit_[a:b]
            cap = acct.leverage * equity / acct.top_n / e
            qty = np.floor(np.minimum(acct.risk * equity / stop_dist[a:b], cap))
            ok = qty >= 1
            gross = s * qty * (x - e)
            costs = np.where(
                ok, trade_costs(np.maximum(qty, 1), e, x, s, acct.plan, ~stopped[a:b]), 0
            )
            pnl = np.where(ok, gross - costs, 0.0)
            equity += pnl.sum()
            keep = np.flatnonzero(ok)
            idx.append(a + keep)
            for k, v in (("qty", qty), ("pnl", pnl), ("costs", costs), ("gross", gross)):
                cols[k].append(v[keep])
        curve.append(equity)
    series = pd.Series(
        [acct.equity, *curve], index=[days[0] - pd.Timedelta(days=1), *days], name="equity"
    )
    if not idx:
        return series, pd.DataFrame()
    rows = np.concatenate(idx)
    fills = live.iloc[rows].reset_index(drop=True)
    fills = fills.assign(**{k: np.concatenate(v) for k, v in cols.items()})
    fills = fills.assign(entry_fill=entry[rows], exit_fill=exit_[rows], stopped=stopped[rows])
    return series, fills


def r_multiple(trades: pd.DataFrame, mode: str = "cons") -> pd.Series:
    """Cost-free P&L per trade in units of the stop distance."""
    move = trades[f"exit_px_{mode}"] - trades["entry_px"]
    return trades["side"] * move / trades["stop_dist"]


# ---------------------------------------------------------------- results bundles


def bundle_trades(fills: pd.DataFrame, rules: OrbRules, mode: str = "path") -> pd.DataFrame:
    """run_portfolio fills -> bundle trade format, with exit times and MAE/MFE from minute bars.

    mae_R / mfe_R: the worst and best price reached between entry and exit, in R, at minute
    resolution (the entry minute's range before the fill is included, so both are slight
    overstatements).
    """
    out = []
    cand = CandidateBars(fills, rules.minutes)
    for day, g in fills.groupby("date"):
        start = F.session_open(day.date())
        for _, r in g.iterrows():
            b = cand.after_or(day, r.ticker)
            k, j = int(r.entry_idx), int(r[f"exit_idx_{mode}"])
            path = b.iloc[k : min(j, len(b) - 1) + 1]
            side, entry = int(r.side), r.entry_fill
            worst = path["low"].min() if side > 0 else path["high"].max()
            best = path["high"].max() if side > 0 else path["low"].min()
            out.append(
                {
                    "entry_time": r.entry_time,
                    "exit_time": b["ts"].iloc[j] if j < len(b) else start + CLOSE_TIME,
                    "symbol": r.ticker,
                    "side": side,
                    "qty": r.qty,
                    "entry_px": entry,
                    "exit_px": r.exit_fill,
                    "gross": r.gross,
                    "costs": r.costs,
                    "pnl": r.pnl,
                    "R": side * (r.exit_fill - entry) / r.stop_dist,
                    "exit_reason": r.get("exit_reason", "stop" if r.stopped else "close"),
                    "stop_px": entry - side * r.stop_dist,
                    "mae_R": side * (entry - worst) / r.stop_dist,
                    "mfe_R": side * (best - entry) / r.stop_dist,
                    "rank": r.get("rank"),
                    "relvol": r.get("relvol"),
                    "atr": r.get("atr"),
                }
            )
    return pd.DataFrame(out)


ORB_CAVEATS = [
    "Minute bars: entry-minute stop touches resolved by the open-low-high-close guess (path).",
    "Short borrow cost not modeled; short-sale-restricted shorts are not excluded.",
    "Many variants (stop widths, top-N, order types, cost plans) were compared on this same "
    "data, so the best-looking setups are optimistic.",
]


def save_orb_run(
    name: str,
    trades: pd.DataFrame,
    acct: Account,
    rules: OrbRules,
    extra: dict | None = None,
    calendar: pd.DatetimeIndex | None = None,
) -> str:
    from horizon_trader.backtest.bundle import save_run

    equity, fills = run_portfolio(trades, acct, calendar)
    spy = benchmark(pd.DatetimeIndex(equity.index[1:]))
    meta = {
        "strategy": "ORB on Stocks in Play (Zarattini, Barbon & Aziz 2024)",
        "params": {"rules": rules.__dict__, "account": acct.__dict__},
        "oos_start": "2024-01-01",
        "chart": "massive_minute",
        "caveats": ORB_CAVEATS,
        "benchmark": "SPY (price only)",
    } | (extra or {})
    path = save_run(name, equity, bundle_trades(fills, rules, acct.same_bar), meta, spy)
    return path.name


# ---------------------------------------------------------------- report

PERIODS = {"all": (None, None), "2021-23": (None, "2023-12-31"), "2024+ (post-pub)": ("2024", None)}


def _slice(series: pd.Series, start: str | None, end: str | None) -> pd.Series:
    """Series within [start, end], keeping the last point before start as the base."""
    if end is not None:
        series = series[series.index <= pd.Timestamp(end)]
    if start is not None:
        i = series.index.searchsorted(pd.Timestamp(start))
        series = series.iloc[max(i - 1, 0) :]
    return series


def _stats(equity: pd.Series, fills: pd.DataFrame) -> dict:
    if len(equity) < 20:
        return {}
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    n = len(fills)
    return summarize(equity) | {
        "trades/yr": n / years,
        "hit": float((fills["pnl"] > 0).mean()) if n else np.nan,
        "$/trade": float(fills["pnl"].mean()) if n else np.nan,
        "costs/trade": float(fills["costs"].mean()) if n else np.nan,
    }


def _rows(label: str, trades: pd.DataFrame, acct: Account) -> list[dict]:
    """One row per period, each starting fresh with the account's capital."""
    rows = []
    for period, (a, b) in PERIODS.items():
        t = trades
        if a is not None:
            t = t[t["date"] >= pd.Timestamp(a)]
        if b is not None:
            t = t[t["date"] <= pd.Timestamp(b)]
        equity, fills = run_portfolio(t, acct)
        rows.append({"setup": label, "period": period} | _stats(equity, fills))
    return rows


def benchmark(days: pd.DatetimeIndex, ticker: str = "SPY") -> pd.Series:
    closes = {d: massive.load_day(d.date(), "day", [ticker])["close"] for d in days}
    return pd.Series({d: float(c.iloc[0]) for d, c in closes.items() if len(c)}, name=ticker)


def signal_report(trades: pd.DataFrame) -> str:
    """Cost-free trade quality in R (multiples of the stop distance), per same-bar convention."""
    t = trades[trades["triggered"]].copy()
    cols = [f"R_{m}" for m in MODES]
    for m in MODES:
        t[f"R_{m}"] = r_multiple(t, m)
    buckets = pd.cut(t["relvol"], [1, 2, 3, 5, 10, 30, np.inf], right=False)
    by_rv = t.groupby(buckets, observed=True)[cols].mean()
    by_rv["count"] = buckets.value_counts()
    by_side = t.groupby(t["side"].map({1: "long", -1: "short"}))[cols].mean()
    by_side.loc["short under SSR"] = t[t["ssr"].fillna(False).astype(bool)][cols].mean()
    years = t["date"].dt.year
    by_year = t.groupby(years)[cols].mean()
    by_year["count"] = years.value_counts()
    best = t["R_path"].sort_values(ascending=False)
    share = best.head(max(len(best) // 20, 1)).sum() / best.sum()
    ambiguous = (t["stopped_cons"] != t["stopped_opt"]).mean()
    return "\n".join(
        [
            f"candidates {len(trades):,}, triggered {len(t):,} ({len(t) / len(trades):.0%}); "
            f"entry minute ambiguous in {ambiguous:.0%} of trades",
            "avg R per trade, before costs:",
            t[cols].mean().round(3).to_frame("all").T.to_string(),
            by_side.round(3).to_string(header=False),
            f"best 5% of trades = {share:.0%} of total R (path)",
            "\nby relative volume:",
            by_rv.round(3).to_string(),
            "\nby year:",
            by_year.round(3).to_string(),
        ]
    )


def stop_sensitivity(stops: list[float], rules: OrbRules = RULES, rebuild: bool = False) -> str:
    """Same strategy at several stop widths. A robustness check, not a way to pick the best.

    R isn't comparable across widths (the unit changes), so trade quality is shown as
    "ATR/trade" = R x stop width, and money results use the same accounts throughout.
    """
    accounts = {
        "$25k top20 0c": Account(plan="fixed"),
        "$25k top20 1c": Account(plan="fixed", slippage=0.01),
        "$25k top20 2c": Account(plan="fixed", slippage=0.02),
        "$5k top2 1c": Account(equity=5_000.0, top_n=2, plan="fixed", slippage=0.01),
    }
    rows = []
    for stop in stops:
        trades = build_trades(replace(rules, stop_atr=stop), rebuild)
        t = trades[(trades["rank"] <= 20) & trades["triggered"]]
        row = {"stop (ATR)": stop, "median stop $": (t["stop_dist"]).median()}
        row["entry-min ambiguous"] = (
            t["stopped_cons"] & (t["exit_idx_cons"] == t["entry_idx"])
        ).mean()
        row["stopped out (path)"] = t["stopped_path"].mean()
        for m in MODES:
            row[f"ATR/trade {m}"] = (r_multiple(t, m) * stop).mean()
        for label, acct in accounts.items():
            s = _stats(*run_portfolio(trades, acct))
            row[f"{label} Sharpe"] = s.get("Sharpe", np.nan)
            if label.startswith("$5k"):
                row[f"{label} CAGR"], row[f"{label} maxDD"] = s.get("CAGR"), s.get("max DD")
        rows.append(row)
    with pd.option_context("display.width", 250, "display.max_columns", 50):
        return pd.DataFrame(rows).set_index("stop (ATR)").round(3).T.to_string()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--minutes", type=int, default=5)
    p.add_argument("--stop-atr", type=float, default=RULES.stop_atr)
    p.add_argument("--stops", help="comma-separated stop widths (in ATR) to compare, e.g. 0.1,0.5")
    p.add_argument("--rebuild", action="store_true", help="recompute the cached trade table")
    p.add_argument("--save", action="store_true", help="save headline runs for the dashboard")
    args = p.parse_args()

    rules = OrbRules(minutes=args.minutes, stop_atr=args.stop_atr)
    if args.stops:
        stops = [float(x) for x in args.stops.split(",")]
        print(stop_sensitivity(stops, rules, args.rebuild))
        return
    trades = build_trades(rules, rebuild=args.rebuild)
    first, last = trades["date"].min(), trades["date"].max()
    print(f"\n{args.minutes}-minute ORB, {first:%Y-%m-%d} .. {last:%Y-%m-%d}, top 20\n")
    print(signal_report(trades[trades["rank"] <= 20]) + "\n")

    paper = Account(plan="paper")
    setups = [(f"paper: $25k top20 paper-costs {m}", replace(paper, same_bar=m)) for m in MODES]
    setups += [
        ("$25k top20 fixed 0c", replace(paper, plan="fixed")),
        ("$25k top20 fixed 1c", replace(paper, plan="fixed", slippage=0.01)),
        ("$25k top20 fixed 2c", replace(paper, plan="fixed", slippage=0.02)),
        ("$25k top20 tiered 1c", replace(paper, plan="tiered", slippage=0.01)),
    ]
    mine = Account(equity=5_000.0, plan="fixed", slippage=0.01)
    for n in (1, 2, 5, 20):
        setups.append((f"$5k top{n} fixed 1c", replace(mine, top_n=n)))
        setups.append((f"$5k top{n} tiered 1c", replace(mine, top_n=n, plan="tiered")))
    rows = [r for label, acct in setups for r in _rows(label, trades, acct)]

    spy = benchmark(pd.DatetimeIndex(sorted(trades["date"].unique())))
    for per, (a, b) in PERIODS.items():
        bench = {"setup": "SPY buy & hold (price only)", "period": per}
        rows.append(bench | summarize(_slice(spy, a, b)))

    table = pd.DataFrame(rows).set_index(["setup", "period"])
    cols = ["CAGR", "Sharpe", "max DD", "trades/yr", "hit", "$/trade", "costs/trade", "final"]
    fmt = {c: "{:.1%}".format for c in ("CAGR", "max DD", "hit")}
    fmt |= {"Sharpe": "{:.2f}".format, "trades/yr": "{:,.0f}".format}
    fmt |= {c: "{:,.2f}".format for c in ("$/trade", "costs/trade")}
    fmt |= {"final": "{:,.0f}".format}
    if args.save:
        for label, acct in (setups[1], setups[4], ("$5k top1 fixed 1c", replace(mine, top_n=1))):
            print("saved", save_orb_run(f"ORB {rules.stop_atr:g}ATR {label}", trades, acct, rules))
    print("same-bar convention: path unless named; each period starts fresh")
    with pd.option_context("display.width", 200, "display.max_rows", 200):
        print(table.reindex(columns=cols).to_string(formatters=fmt, na_rep="-"))


if __name__ == "__main__":
    main()
