"""Does the time of day you buy matter for 1-5 day swing trades? (research/entry_timing)

    uv run python -m horizon_trader.intraday.entry_timing [--rebuild]

Reads each Massive minute file once for all tickers (parallel), keeps the open of the bars at
the entry times, and caches them in data/massive/derived/entry_times.parquet. Pre-registered
rules: research/entry_timing/protocol.md.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader import config
from horizon_trader.config import data_dir
from horizon_trader.datasources import massive
from horizon_trader.intraday.orb import workers

TICKERS = ["SPY", "QQQ", "SMH", "TQQQ", "SOXL", "NVDA", "AMD", "AVGO", "MU", "TSLA", "META"]
TIMES = ["09:35", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "15:30", "15:55"]
HOLDS = [1, 3, 5]
SPLIT_GAP = 0.35
HALVES = {"2021-23": ("2021-01-01", "2023-12-31"), "2024+": ("2024-01-01", "2099-12-31")}
OUT = config.REPO_ROOT / "research" / "entry_timing"


def cache_path() -> Path:
    return data_dir() / "massive" / "derived" / "entry_times.parquet"


def read_day(d: date) -> pd.DataFrame:
    """Open of each entry-time bar for every ticker on day d, plus the official open/close."""
    filt = [("ticker", "in", TICKERS)]
    m = pd.read_parquet(massive.local_path("minute", d), filters=filt)
    m["hhmm"] = m["ts"].dt.strftime("%H:%M")
    px = m[m["hhmm"].isin(TIMES)].pivot_table(index="ticker", columns="hhmm", values="open")
    day = massive.load_day(d, "day", TICKERS).set_index("ticker")[["open", "close"]]
    out = day.rename(columns={"open": "day_open", "close": "day_close"}).join(px, how="left")
    return out.reset_index().assign(date=pd.Timestamp(d))


def build(rebuild: bool = False) -> pd.DataFrame:
    path = cache_path()
    old = None if rebuild or not path.exists() else pd.read_parquet(path)
    have = set() if old is None else set(old["date"].dt.date)
    days = [d for d in massive.local_days("minute") if d not in have]
    days = [d for d in days if massive.local_path("day", d).exists()]
    if days:
        print(f"reading {len(days)} minute files with {workers()} workers", flush=True)
        with ProcessPoolExecutor(workers()) as ex:
            new = list(ex.map(read_day, days, chunksize=8))
        df = pd.concat([x for x in (old, *new) if x is not None], ignore_index=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
    else:
        df = old
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


def returns(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (ticker, entry day, hold N): return from each entry time to close of day N."""
    rows = []
    for t, g in df.groupby("ticker"):
        g = g.set_index("date").sort_index()
        gap = g["day_open"] / g["day_close"].shift(1) - 1
        split = (gap.abs() > SPLIT_GAP).astype(int)
        for n in HOLDS:
            exit_close = g["day_close"].shift(-n)
            # a split on any day from entry+1 to exit (or the entry day itself) poisons the window
            bad = split.rolling(n + 1).sum().shift(-n) > 0
            r = pd.DataFrame({e: exit_close / g[e] - 1 for e in TIMES})
            r["next_open"] = exit_close / g["day_open"].shift(-1) - 1
            r["close_t0"] = exit_close / g["day_close"] - 1  # buying at today's close (auction)
            r["move_to_1500"] = g["15:00"] / g["day_close"].shift(1) - 1
            r["rest_of_day_1500"] = g["day_close"] / g["15:00"] - 1
            r = r[~bad & exit_close.notna()]
            rows.append(r.assign(ticker=t, hold=n).reset_index())
    return pd.concat(rows, ignore_index=True)


def tstat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / (x.std() / np.sqrt(len(x)))) if len(x) > 2 and x.std() > 0 else np.nan


def pooled(r: pd.DataFrame, col: str, hold: int) -> pd.Series:
    """Equal-weight average across tickers per day (so the t-stat isn't inflated by 11 names
    moving together)."""
    sub = r[r["hold"] == hold]
    return sub.groupby("date")[col].mean()


def tests(r: pd.DataFrame) -> pd.DataFrame:
    out = []
    for name, (a, b) in HALVES.items():
        sub = r[(r["date"] >= a) & (r["date"] <= b)]
        h1 = pooled(sub.assign(d=sub["15:00"] - sub["09:35"]), "d", 1)
        h2 = pooled(sub.assign(d=sub["15:00"] - sub["next_open"]), "d", 1)
        for test, s in (("H1: 15:00 minus 9:35", h1), ("H2: 15:00 minus next open", h2)):
            out.append({"test": test, "period": name, "days": len(s),
                        "mean_bp": s.mean() * 1e4, "t": tstat(s)})  # fmt: skip
    t = pd.DataFrame(out)
    verdict = t.groupby("test").apply(lambda g: bool(((g["mean_bp"] > 0) & (g["t"] > 2)).all()))
    return t.assign(passed=t["test"].map(verdict))


def by_time(r: pd.DataFrame) -> pd.DataFrame:
    """Mean return (bp) to the fixed exit by entry time, pooled and per ticker, for each hold."""
    cols = [*TIMES, "close_t0", "next_open"]
    rows = []
    for n in HOLDS:
        sub = r[r["hold"] == n]
        pool = sub.groupby("date")[cols].mean()
        rows.append({"ticker": "ALL (pooled)", "hold": n, **(pool.mean() * 1e4).round(1)})
        for t, g in sub.groupby("ticker"):
            rows.append({"ticker": t, "hold": n, **(g[cols].mean() * 1e4).round(1)})
    return pd.DataFrame(rows)


def intraday_profile(r: pd.DataFrame) -> pd.DataFrame:
    """Mean return (bp) from each entry time to the SAME day's close, i.e. the part of the
    swing trade that depends on the entry time. Uses hold 1 rows (one per day)."""
    sub = r[r["hold"] == 1]
    cols = [*TIMES]
    # (exit/entry_t) / (exit/close_t0) - 1 = close_t0 / entry_t - 1
    prof = pd.DataFrame({c: (1 + sub[c]) / (1 + sub["close_t0"]) - 1 for c in cols})
    prof[["ticker", "date"]] = sub[["ticker", "date"]]
    rows = []
    for name, (a, b) in {"all": ("2000", "2099"), **HALVES}.items():
        p = prof[(prof["date"] >= a) & (prof["date"] <= b)]
        pool = p.groupby("date")[cols].mean()
        rows.append({"period": name, "stat": "mean bp", **(pool.mean() * 1e4).round(1)})
        rows.append({"period": name, "stat": "t", **pool.apply(tstat).round(2)})
    return pd.DataFrame(rows)


def timing_luck(r: pd.DataFrame) -> pd.DataFrame:
    """Average |entry price at time t / the day's mean entry price - 1| in %: how far one
    trade's entry can land from a typical entry that day."""
    sub = r[r["hold"] == 1]
    entries = pd.DataFrame({c: 1 / (1 + sub[c]) for c in TIMES})  # proportional to entry price
    dev = entries.div(entries.mean(axis=1), axis=0) - 1
    dev["ticker"] = sub["ticker"].to_numpy()
    out = dev.groupby("ticker")[TIMES].apply(lambda g: g.abs().mean().mean() * 100)
    return out.rename("avg_abs_gap_pct").round(2).reset_index()


def conditional(r: pd.DataFrame) -> pd.DataFrame:
    """Exploratory: after a >2% move by 15:00, what happens into the close and the next day?"""
    sub = r[r["hold"] == 1].copy()
    labels = ["down >2% by 15:00", "within ±2%", "up >2% by 15:00"]
    sub["bucket"] = pd.cut(sub["move_to_1500"], [-np.inf, -0.02, 0.02, np.inf], labels=labels)
    g = sub.groupby("bucket", observed=True)
    return pd.DataFrame({
        "n": g.size(),
        "15:00 to close, bp": g["rest_of_day_1500"].mean() * 1e4,
        "t (to close)": g["rest_of_day_1500"].apply(tstat),
        "15:00 to next close, bp": g["15:00"].mean() * 1e4,
        "t (to next close)": g["15:00"].apply(tstat),
    }).round(2).reset_index()  # fmt: skip


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rebuild", action="store_true")
    a = p.parse_args()
    df = build(a.rebuild)
    r = returns(df)
    first, last = r["date"].min().date(), r["date"].max().date()
    OUT.mkdir(parents=True, exist_ok=True)
    results = {
        "tests": tests(r), "by_time": by_time(r), "intraday_profile": intraday_profile(r),
        "timing_luck": timing_luck(r), "conditional_exploratory": conditional(r),
    }  # fmt: skip
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    print(f"{df['ticker'].nunique()} tickers, {first} to {last}")
    for name, t in results.items():
        t.to_csv(OUT / f"{name}.csv", index=False)
        print(f"\n== {name}\n{t.to_string(index=False)}")


if __name__ == "__main__":
    main()
