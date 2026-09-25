"""Measure ORB fill slippage from 1-second bars instead of assuming it.

    uv run python -m horizon_trader.intraday.slippage [--top 2] [--stop 1.0]

For every entry (and every stop-out), fetches the 1-second bars of that minute from Massive's
REST API (cached under <data_dir>/massive/seconds/), finds the second in which the stop order
triggered, and compares plausible fill prices with the price the minute-bar backtest assumed:

  vwap       volume-weighted price of the trigger second (a typical fill)
  next_open  first trade of the following second (a fill ~1 second after the trigger)
  extreme    the worst print within the trigger second (a bad-luck fill)

Positive slippage = worse for us. What second bars can't show is the bid/ask spread: a real
stop order fills at the ask (buy) or bid (sell), which can be worse than any printed trade.
So these numbers are a floor on real slippage, and paper trading remains the real test.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import numpy as np
import pandas as pd

from horizon_trader.config import data_dir
from horizon_trader.data import massive
from horizon_trader.data.massive_ref import API, _http_get
from horizon_trader.intraday import features as F
from horizon_trader.intraday import orb

MINUTE = pd.Timedelta(minutes=1)
TICK = 0.01  # a resting limit order only counts as filled once price trades through it


def _cache_path(ticker: str, minute: pd.Timestamp):
    return (
        data_dir()
        / "massive"
        / "seconds"
        / f"{minute:%Y-%m-%d}"
        / f"{ticker}_{minute:%H%M}.parquet"
    )


def fetch_seconds(ticker: str, minute: pd.Timestamp, fetch=_http_get) -> pd.DataFrame:
    """Unadjusted 1-second bars (ts, open, high, low, close, volume, vwap) of one minute, cached."""
    path = _cache_path(ticker, minute)
    if path.exists():
        return pd.read_parquet(path)
    a = int(minute.timestamp() * 1000)
    url = f"{API}/v2/aggs/ticker/{ticker}/range/1/second/{a}/{a + 59_999}"
    res = fetch(f"{url}?adjusted=false&sort=asc&limit=50000").get("results", [])
    cols = {
        "t": "ts",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "vw": "vwap",
    }
    df = pd.DataFrame(res).reindex(columns=list(cols)).rename(columns=cols)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert(massive.TZ)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def fill_slippage(secs: pd.DataFrame, direction: int, trigger: float, modeled: float) -> dict:
    """Slippage of a stop order that buys (direction +1) or sells (-1) once price reaches `trigger`.

    `modeled` is the fill the minute-bar backtest assumed. Returns NaNs if the seconds never
    reach the trigger (the two data sets disagree slightly now and then).
    """
    nan = {"vwap": np.nan, "next_open": np.nan, "extreme": np.nan, "trigger_sec_volume": np.nan}
    if secs.empty:
        return nan
    hit = secs["high"] >= trigger if direction > 0 else secs["low"] <= trigger
    if not hit.any():
        return nan
    i = int(np.argmax(hit.to_numpy()))
    row = secs.iloc[i]
    extreme = row["high"] if direction > 0 else row["low"]
    nxt = secs["open"].iloc[i + 1] if i + 1 < len(secs) else row["close"]

    def worse(px: float) -> float:
        # positive = paid more (buy) / received less (sell). A stop order turns into a market
        # order at the trigger and fills at the ask/bid, never better than the modeled price
        return max(direction * (px - modeled), 0.0)

    vwap = row["vwap"] if pd.notna(row["vwap"]) else row["close"]
    return {
        "vwap": worse(vwap),
        "next_open": worse(nxt),
        "extreme": worse(extreme),
        "trigger_sec_volume": row["volume"],
    }


def exit_minutes(trades: pd.DataFrame, rules: orb.OrbRules, mode: str = "path") -> pd.Series:
    """Timestamp of the minute each stopped trade was stopped in (from the local minute bars)."""
    out = {}
    stopped = trades[trades[f"stopped_{mode}"].astype(bool)]
    for (day, ticker), g in stopped.groupby(["date", "ticker"]):
        start = F.session_open(day.date()) + pd.Timedelta(minutes=rules.minutes)
        end = F.session_open(day.date()) + orb.CLOSE_TIME
        window = [("ticker", "==", ticker), ("ts", ">=", start), ("ts", "<", end)]
        bars = pd.read_parquet(massive.local_path("minute", day.date()), filters=window)
        ts = bars.sort_values("ts")["ts"].reset_index(drop=True)
        for idx, j in g[f"exit_idx_{mode}"].items():
            out[idx] = ts.iloc[int(j)]
    return pd.Series(out, dtype=f"datetime64[ns, {massive.TZ}]")


def measure(trades: pd.DataFrame, rules: orb.OrbRules, workers: int = 8) -> pd.DataFrame:
    """Entry and stop-exit slippage (in $/share) for each trade, from 1-second bars."""
    t = trades.copy()
    t["exit_time"] = exit_minutes(t, rules)
    jobs = [(i, "entry", r.ticker, r.entry_time) for i, r in t.iterrows()]
    jobs += [(i, "exit", r.ticker, r.exit_time) for i, r in t.iterrows() if pd.notna(r.exit_time)]

    minutes = sorted({(tk, mi) for _, _, tk, mi in jobs})
    with ThreadPoolExecutor(max_workers=workers) as pool:  # each minute fetched once
        for n, _ in enumerate(pool.map(lambda k: fetch_seconds(*k), minutes), 1):
            if n % 250 == 0 or n == len(minutes):
                print(f"  {n}/{len(minutes)} minutes of second bars", flush=True)

    results = {}
    for i, leg, ticker, minute in jobs:
        secs, r = fetch_seconds(ticker, minute), t.loc[i]
        if leg == "entry":
            results[(i, leg)] = fill_slippage(secs, r.side, r.level, r.entry_px)
        else:
            results[(i, leg)] = fill_slippage(secs, -r.side, r.stop_px, r.exit_px_path)
    for (i, leg), res in results.items():
        for k, v in res.items():
            t.loc[i, f"{leg}_{k}"] = v
    return t


def summary(m: pd.DataFrame) -> str:
    lines = []
    for leg in ("entry", "exit"):
        cols = [f"{leg}_{k}" for k in ("vwap", "next_open", "extreme")]
        x = m[cols].dropna(how="all") * 100  # cents
        if x.empty:
            continue
        pct = (m[cols].div(m["entry_px"], axis=0) * 1e4).dropna(how="all")  # basis points
        q = x.quantile([0.25, 0.5, 0.75, 0.9]).T
        q.insert(0, "mean", x.mean())
        q["mean bps"] = pct.mean()
        lines += [f"\n{leg} slippage, cents/share ({len(x):,} fills; + = worse than backtest):"]
        lines += [q.round(2).to_string()]
    return "\n".join(lines)


# ---------------------------------------------------------------- stop-limit entries


def limit_fill_in_seconds(secs: pd.DataFrame, side: int, trigger: float, limit: float):
    """Fill price of a stop-limit order within the trigger minute, or None.

    The order goes live once a trade reaches `trigger` and can fill from the next second on
    (about one second of latency) once a trade prints at least a tick through `limit`
    (a mere touch may fill other orders queued ahead of ours).
    """
    if secs.empty:
        return None
    hit = secs["high"] >= trigger if side > 0 else secs["low"] <= trigger
    if not hit.any():
        return None
    after = secs.iloc[int(np.argmax(hit.to_numpy())) + 1 :]
    ok = after["low"] <= limit - TICK if side > 0 else after["high"] >= limit + TICK
    if not ok.any():
        return None
    # without quotes we can't see the ask/bid, so assume the worst price the order allows
    return limit


def exit_from(o, h, low, j: int, fill: float, side: int, stop_dist: float, close_px: float):
    """(exit price, stopped, exit index) for a position filled in minute j (index len(o) =
    the close). Stop-market exit, else the close.

    A stop touched in the fill minute counts (with the 1 ATR stop this is ~never ambiguous).
    """
    stop = fill - side * stop_dist
    adverse = low[j:] <= stop if side > 0 else h[j:] >= stop
    if not adverse.any():
        return close_px, False, len(o)
    i = j + int(np.argmax(adverse))
    if i == j:
        return stop, True, i
    return (min(o[i], stop) if side > 0 else max(o[i], stop)), True, i


def stop_limit_trades(m: pd.DataFrame, rules: orb.OrbRules, offset: float) -> pd.DataFrame:
    """Re-simulate entries as stop-limit orders with limit = trigger +/- `offset` dollars.

    Unfilled in the trigger minute, the order keeps working and fills later in the day if price
    comes back to the limit (on minute bars). Never filled = no trade. Stops stay stop-market.
    Fills are assumed at the limit price itself (the worst allowed), since second bars show
    trades, not the bid/ask a real order would fill against.
    """
    out = []
    for (day, ticker), g in m.groupby(["date", "ticker"]):
        start = F.session_open(day.date()) + pd.Timedelta(minutes=rules.minutes)
        end = F.session_open(day.date()) + orb.CLOSE_TIME
        window = [("ticker", "==", ticker), ("ts", ">=", start), ("ts", "<", end)]
        bars = pd.read_parquet(massive.local_path("minute", day.date()), filters=window)
        bars = bars.sort_values("ts")
        o, h, lo = (bars[f].to_numpy(float) for f in ("open", "high", "low"))
        for _, r in g.iterrows():
            side, k = int(r.side), int(r.entry_idx)
            limit = r.level + side * offset
            fill, j = (
                limit_fill_in_seconds(fetch_seconds(ticker, r.entry_time), side, r.level, limit),
                k,
            )
            if fill is None:  # keeps working: fills if price comes back to the limit
                back = lo[k + 1 :] <= limit - TICK if side > 0 else h[k + 1 :] >= limit + TICK
                if back.any():
                    j = k + 1 + int(np.argmax(back))
                    fill = limit
            row = r.copy()
            row["triggered"] = fill is not None
            row["fill_delay_min"] = j - k if fill is not None else np.nan
            if fill is not None:
                px, stopped, x = exit_from(o, h, lo, j, fill, side, r.stop_dist, r.close)
                row["entry_px"], row["exit_px_path"], row["stopped_path"] = fill, px, stopped
                row["entry_idx"], row["exit_idx_path"] = j, x
                row["entry_time"] = bars["ts"].iloc[j]
            out.append(row)
    return pd.DataFrame(out)


def measured_variants(
    m: pd.DataFrame, rules: orb.OrbRules, offsets: tuple[int, ...] = (0, 2, 5, 10)
) -> dict[str, pd.DataFrame]:
    """Trade tables with measured fills: stop-market entries, and stop-limit entries at each
    offset (cents). Stop-outs use each trade's measured slippage, or the mean if unmeasured."""
    exit_slip = m["exit_next_open"].mean()
    variants = {
        "stop-market": m.assign(
            entry_slip=m["entry_next_open"].fillna(m["entry_next_open"].mean()),
            exit_slip=m["exit_next_open"].fillna(exit_slip),
        )
    }
    for cents in offsets:
        v = stop_limit_trades(m, rules, cents / 100).assign(entry_slip=0.0, exit_slip=exit_slip)
        variants[f"stop-limit +{cents}c"] = v
    return variants


def compare(m: pd.DataFrame, rules: orb.OrbRules, top: int, calendar: pd.DatetimeIndex) -> str:
    """Account size x commission plan x entry order type, using measured fills."""
    variants = measured_variants(m, rules)
    fill_rates = {}
    for name, v in variants.items():
        if name == "stop-market":
            continue
        filled = v["triggered"].astype(bool)
        fill_rates[name] = {
            "filled": filled.mean(),
            "in trigger minute": (v["fill_delay_min"] == 0).mean(),
            "avg R filled": orb.r_multiple(v[filled], "path").mean(),
            "avg R missed (as market)": orb.r_multiple(m.loc[v.index[~filled]], "path").mean(),
        }
    rows = []
    for name, v in variants.items():
        for equity in (5_000.0, 20_000.0):
            for plan in ("fixed", "tiered", "lite"):
                for n in range(1, top + 1):
                    acct = orb.Account(equity=equity, top_n=n, plan=plan, slippage=None)
                    s = orb._stats(*orb.run_portfolio(v, acct, calendar))
                    rows.append(
                        {"entry": name, "top": n, "account": f"${equity / 1000:.0f}k {plan}"}
                        | {k: s.get(k) for k in ("CAGR", "Sharpe", "max DD", "costs/trade")}
                    )
    df = pd.DataFrame(rows)
    lines = ["fill behaviour of stop-limit entries (vs the stop-market trades they replace):"]
    lines.append(pd.DataFrame(fill_rates).T.round(3).to_string())
    for col, fmt in (("CAGR", "{:.1%}"), ("Sharpe", "{:.2f}"), ("max DD", "{:.0%}")):
        pv = df.pivot_table(index=["entry", "top"], columns="account", values=col, sort=False)
        lines += [f"\n{col}:", pv.map(fmt.format).to_string()]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--top", type=int, default=2, help="measure trades ranked <= this")
    p.add_argument("--stop", type=float, default=1.0, help="stop width in ATR (exit legs)")
    p.add_argument("--equity", type=float, default=5_000.0)
    p.add_argument("--compare", action="store_true", help="account size x plan x order type")
    p.add_argument("--save", action="store_true", help="save top-1 runs for the dashboard")
    args = p.parse_args()

    rules = replace(orb.RULES, stop_atr=args.stop)
    trades = orb.build_trades(rules)
    calendar = pd.DatetimeIndex(sorted(trades["date"].unique()))  # every day of the test
    t = trades[(trades["rank"] <= args.top) & trades["triggered"]]
    print(f"measuring {len(t):,} trades (rank <= {args.top}, stop {args.stop} ATR)")
    m = measure(t, rules)
    if args.save:
        variants = measured_variants(m, rules, offsets=(0,))
        caveat = (
            "Fills measured from 1-second trade bars (no quotes); stop-limit fills are "
            "assumed at the limit price, stop-market fills at the next second's open."
        )
        accounts = {
            "$5k fixed": (5_000.0, "fixed"),
            "$20k fixed": (20_000.0, "fixed"),
            "$5k lite": (5_000.0, "lite"),
        }
        for vname, v in variants.items():
            for label, (equity, plan) in accounts.items():
                acct = orb.Account(equity=equity, top_n=1, plan=plan, slippage=None)
                name = f"ORB top1 {args.stop:g}ATR {vname} {label}"
                extra = {"caveats": [*orb.ORB_CAVEATS, caveat]}
                print("saved", orb.save_orb_run(name, v, acct, rules, extra, calendar))
    if args.compare:
        print(compare(m, rules, args.top, calendar))
        return
    print(summary(m))

    # rerun the portfolio with each trade's measured slippage in place of a flat assumption
    rows = []
    for est in ("vwap", "next_open", "extreme"):
        mm = m.assign(
            entry_slip=m[f"entry_{est}"].fillna(m[f"entry_{est}"].median()),
            exit_slip=m[f"exit_{est}"].fillna(m[f"exit_{est}"].median()).fillna(0.0),
        )
        for n in range(1, args.top + 1):
            acct = orb.Account(equity=args.equity, top_n=n, plan="fixed", slippage=None)
            s = orb._stats(*orb.run_portfolio(mm, acct, calendar))
            rows.append({"slippage": f"measured ({est})", "top": n} | s)
    for c in (0.01, 0.02, 0.03):
        for n in range(1, args.top + 1):
            acct = orb.Account(equity=args.equity, top_n=n, plan="fixed", slippage=c)
            rows.append(
                {"slippage": f"flat {c * 100:.0f}c", "top": n}
                | orb._stats(*orb.run_portfolio(t, acct, calendar))
            )
    cols = ["CAGR", "Sharpe", "max DD", "trades/yr", "$/trade", "costs/trade"]
    table = pd.DataFrame(rows).set_index(["slippage", "top"])[cols]
    print(f"\n${args.equity:,.0f} account, IBKR Fixed, stop {args.stop} ATR:")
    print(table.round(3).to_string())


if __name__ == "__main__":
    main()
