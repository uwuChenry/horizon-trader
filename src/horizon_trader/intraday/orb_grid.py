"""ORB parameter grid: every combination of stop width, profit target, relative-volume filter,
entry cutoff, slippage/order-type scenario and account size, evaluated out of sample.

    uv run python -m horizon_trader.intraday.orb_grid [--workers N] [--save]

Signal: the paper's selection, top-1 stock by relative volume, long/short from the first
5-minute candle, entry on a break of its high/low. Everything below varies around that.

Grid (6 x 5 x 4 x 4 = 480 configurations per scenario and account size):
  stop       0.25 / 0.5 / 0.75 / 1 / 1.5 / 2 ATR from the fill
  target     hold to the close, or take profit at 1 / 2 / 3 / 5 R (the reward:risk ratio)
  relvol     any, or the day's top stock must have relative volume >= 5 / 8 / 12
  cutoff     any entry time, or no entries after 10:00 / 10:30 / 11:00
Scenarios (entry order + slippage per share; targets are limit orders, the close is MOC):
  0c (paper)               stop-market entry, 0c in, 0c on stop-outs: the paper's assumption
  1c                       stop-market entry, 1c in and out: liquid large-cap best case
  measured, stop-market    4.5c in, 4c on stop-outs: measured on these trades (1-second bars)
  measured, stop-limit     limit at the trigger (fills at the limit, can miss), 4c stop-outs
Accounts: $5k and $20k, 1% risk per trade, IBKR Pro Tiered costs.

Protocol, fixed before the run:
  train = 2021-10-22 .. 2023-12-31, test = 2024-01-01 .. 2026-09-24.
  1. In each scenario x account, pick the config with the best TRAIN Sharpe (at least 100
     train trades). Its TEST Sharpe, not its train Sharpe, is the honest estimate.
  2. Compare it with the baseline (1 ATR, hold, any relvol, any time) and the median config.
  3. Spearman rank correlation of train vs test Sharpe across configs: near zero means the
     in-sample ranking carries no information, i.e. "optimizing" is fitting noise.
  4. Deflated Sharpe (Bailey & Lopez de Prado 2014) of the best full-period config, for 480
     trials: the probability its Sharpe beats what the best of 480 random tries would show.
  5. Ablation: from the baseline change one parameter at a time; from the best-train config
     revert one parameter at a time.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import time
from itertools import product
from time import perf_counter

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.config import REPO_ROOT
from horizon_trader.data import massive
from horizon_trader.intraday import orb
from horizon_trader.intraday import orb_ideas as I
from horizon_trader.intraday.slippage import TICK, fetch_seconds, limit_fill_second

STOPS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
TARGETS = (None, 1.0, 2.0, 3.0, 5.0)
RELVOLS = (1.0, 5.0, 8.0, 12.0)
CUTOFFS = (None, time(10), time(10, 30), time(11))
CAPITALS = (5_000.0, 20_000.0)
SCENARIOS = {  # name: (entry order, entry slippage $/share, stop-out slippage $/share)
    "0c (paper)": ("market", 0.0, 0.0),
    "1c": ("market", 0.01, 0.01),
    "measured, stop-market": ("market", 0.045, 0.04),
    "measured, stop-limit": ("limit", 0.0, 0.04),
}
PARAMS = ("stop", "target", "relvol", "cutoff")
BASELINE = {"stop": 1.0, "target": None, "relvol": 1.0, "cutoff": None}
TRAIN = ("2021-01-01", "2023-12-31")
TEST = ("2024-01-01", "2100-01-01")
MIN_TRAIN_TRADES = 100
N_CONFIGS = len(STOPS) * len(TARGETS) * len(RELVOLS) * len(CUTOFFS)


def label(stop, target, relvol, cutoff) -> str:
    t = "hold to close" if target is None or pd.isna(target) else f"target {target:g}R"
    rv = "any relvol" if relvol <= 1 else f"relvol >= {relvol:g}"
    c = "any entry time" if cutoff is None or pd.isna(cutoff) else f"entries by {cutoff:%H:%M}"
    return f"stop {stop:g} ATR · {t} · {rv} · {c}"


# ---------------------------------------------------------------- simulation


def simulate_config(
    picked: pd.DataFrame,
    stop_mult: float,
    target: float | None,
    entry: str,
    bars: I.Bars,
    secs: dict,
) -> pd.DataFrame:
    """Trades for one (stop, target, entry order) on the top-1 selection. Inside the fill
    minute, stops and targets are checked on the 1-second bars after the fill (stop first when
    one second spans both); later minutes use minute bars (see orb_ideas.manage_exit)."""
    rule, r_mult = ("target", target) if target else ("hold", 0.0)
    rows = []
    for r in picked.itertuples():
        ts, o, h, lo = bars.get(r.date, r.ticker)
        side, k, level, dist = int(r.side), int(r.entry_idx), r.level, stop_mult * r.atr
        sec_bars = secs.get((r.ticker, r.entry_time))
        has_secs = sec_bars is not None and not sec_bars.empty
        fill, j, sec = None, k, None
        if entry == "limit":  # stop-limit at the trigger: fills at the limit, can miss
            sec = limit_fill_second(sec_bars, side, level, level) if has_secs else None
            if sec is not None:
                fill = level
            else:
                back = lo[k + 1 :] <= level - TICK if side > 0 else h[k + 1 :] >= level + TICK
                if not back.any():
                    continue
                fill, j = level, k + 1 + int(np.argmax(back))
        else:  # stop-market: fills at the trigger second's price, never misses
            if has_secs:
                hit = sec_bars["high"] >= level if side > 0 else sec_bars["low"] <= level
                if hit.any():
                    sec = int(np.argmax(hit.to_numpy()))
                    first = sec_bars["open"].iloc[sec]
                    fill = max(level, first) if side > 0 else min(level, first)
            if fill is None:
                fill = r.entry_px  # no second bars: the minute-bar fill
        early = None
        if sec is not None:
            stop, tgt = fill - side * dist, fill + side * (target or 0.0) * dist
            after = sec_bars.iloc[sec + 1 :]
            for so, sh, sl in zip(after["open"], after["high"], after["low"], strict=True):
                if (sl <= stop) if side > 0 else (sh >= stop):
                    early = (min(so, stop) if side > 0 else max(so, stop)), True
                    break
                if target and ((sh >= tgt + TICK) if side > 0 else (sl <= tgt - TICK)):
                    early = (max(so, tgt) if side > 0 else min(so, tgt)), False
                    break
        if early is not None:
            (px, stopped), x = early, j
        else:
            px, stopped, x = I.manage_exit(
                o, h, lo, j, fill, side, dist, r.close, rule, r_mult, check_fill_minute=sec is None
            )
        t = pd.Timestamp(ts[j])
        rows.append(
            {
                "date": r.date,
                "ticker": r.ticker,
                "rank": 1,
                "triggered": True,
                "side": side,
                "relvol": r.relvol,
                "atr": r.atr,
                "level": level,
                "close": r.close,
                "entry_px": fill,
                "entry_idx": j,
                "stop_dist": dist,
                "entry_time": t if t.tzinfo else t.tz_localize("UTC").tz_convert(massive.TZ),
                "exit_px_path": px,
                "stopped_path": stopped,
                "exit_idx_path": x,
                "exit_reason": "stop" if stopped else ("close" if x >= len(o) else "target"),
            }
        )
    return pd.DataFrame(rows)


def filtered(sim: pd.DataFrame, relvol: float, cutoff: time | None) -> pd.DataFrame:
    t = sim[sim["relvol"] >= relvol]
    if cutoff is not None and len(t):
        t = t[t["entry_time"].dt.time <= cutoff]
    return t


def metrics(equity: pd.Series, fills: pd.DataFrame, prefix: str) -> dict:
    r = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    sd = r.std()
    pnl = fills["pnl"] if len(fills) else pd.Series(dtype=float)
    losses = -pnl[pnl < 0].sum()
    out = {
        "Sharpe": r.mean() / sd * np.sqrt(252) if sd else np.nan,
        "CAGR": (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1,
        "max DD": (equity / equity.cummax() - 1).min(),
        "trades": len(pnl),
        "win rate": (pnl > 0).mean() if len(pnl) else np.nan,
        "profit factor": pnl[pnl > 0].sum() / losses if losses else np.nan,
        "daily SR": r.mean() / sd if sd else np.nan,
    }
    if len(fills):
        move = fills["side"] * (fills["exit_fill"] - fills["entry_fill"])
        out["avg R"] = (move / fills["stop_dist"]).mean()
    return {f"{prefix} {k}": v for k, v in out.items()}


_BARS: I.Bars | None = None
_SECS: dict | None = None


def _init(bars: I.Bars, secs: dict) -> None:
    global _BARS, _SECS
    _BARS, _SECS = bars, secs


def _job(job):
    stop, target, entry, picked, calendars = job
    sim = simulate_config(picked, stop, target, entry, _BARS, _SECS)
    rows = []
    for relvol, cutoff in product(RELVOLS, CUTOFFS):
        t = filtered(sim, relvol, cutoff)
        for scen, (order, slip_in, slip_out) in SCENARIOS.items():
            if order != entry:
                continue
            t2 = t.assign(entry_slip=slip_in, exit_slip=slip_out)
            for cap in CAPITALS:
                acct = orb.Account(equity=cap, top_n=1, plan="tiered", slippage=None)
                row = {
                    "stop": stop,
                    "target": target,
                    "relvol": relvol,
                    "cutoff": cutoff,
                    "scenario": scen,
                    "capital": cap,
                }
                for period, cal in calendars.items():
                    tt = t2[t2["date"].isin(cal)] if len(t2) else t2
                    if len(tt):
                        eq, fills = orb.run_portfolio(tt, acct, cal)
                    else:
                        eq, fills = pd.Series(cap, index=cal), pd.DataFrame()
                    row |= metrics(eq, fills, period)
                rows.append(row)
    return rows, (stop, target, entry), sim


def run_grid(n_workers: int | None = None):
    trades = orb.build_trades(I.RULES)
    base = I.select(trades, I.IDEAS[0], pd.Series(dtype=int))
    picked = base[base["triggered"].astype(bool)]
    cal = pd.DatetimeIndex(sorted(trades["date"].unique()))
    calendars = {
        "train": cal[(cal >= TRAIN[0]) & (cal <= TRAIN[1])],
        "test": cal[(cal >= TEST[0]) & (cal <= TEST[1])],
        "all": cal,
    }
    bars = I.Bars.load(trades, sorted({(r.date, r.ticker) for r in picked.itertuples()}))
    secs = {
        (r.ticker, r.entry_time): fetch_seconds(r.ticker, r.entry_time) for r in picked.itertuples()
    }
    jobs = [
        (s, t, e, picked, calendars) for s, t, e in product(STOPS, TARGETS, ("market", "limit"))
    ]
    n = min(len(jobs), orb.workers(n_workers))
    with ProcessPoolExecutor(max_workers=n, initializer=_init, initargs=(bars, secs)) as pool:
        out = list(pool.map(_job, jobs))
    results = pd.DataFrame([row for rows, _, _ in out for row in rows])
    sims = {key: sim for _, key, sim in out}
    return results, sims, calendars


# ---------------------------------------------------------------- analysis


def is_baseline(df: pd.DataFrame) -> pd.Series:
    return (df["stop"] == 1.0) & df["target"].isna() & (df["relvol"] == 1.0) & df["cutoff"].isna()


def summary(results: pd.DataFrame) -> pd.DataFrame:
    """Best-by-train config per scenario x account, judged on the test period."""
    rows = []
    for (scen, cap), g in results.groupby(["scenario", "capital"], sort=False):
        base = g[is_baseline(g)].iloc[0]
        ok = g[g["train trades"] >= MIN_TRAIN_TRADES]
        best = ok.loc[ok["train Sharpe"].idxmax()]
        rho = g["train Sharpe"].rank().corr(g["test Sharpe"].rank())  # Spearman, no scipy
        rows.append(
            {
                "scenario": scen,
                "account": f"${cap / 1000:.0f}k",
                "best config (chosen on train)": label(
                    best.stop, best.target, best.relvol, best.cutoff
                ),
                "best: train Sharpe": best["train Sharpe"],
                "best: test Sharpe": best["test Sharpe"],
                "best: test CAGR": best["test CAGR"],
                "best: test max DD": best["test max DD"],
                "baseline: train Sharpe": base["train Sharpe"],
                "baseline: test Sharpe": base["test Sharpe"],
                "baseline: test CAGR": base["test CAGR"],
                "median config: test Sharpe": g["test Sharpe"].median(),
                "configs beating baseline on test": (g["test Sharpe"] > base["test Sharpe"]).mean(),
                "train-test rank corr.": rho,
            }
        )
    return pd.DataFrame(rows)


def deflated(results: pd.DataFrame, sims: dict, calendars: dict, scen: str, cap: float) -> dict:
    """Deflated Sharpe of the best full-period config in one scenario x account."""
    g = results[(results["scenario"] == scen) & (results["capital"] == cap)]
    best = g.loc[g["all Sharpe"].idxmax()]
    order, slip_in, slip_out = SCENARIOS[scen]
    target = None if pd.isna(best.target) else best.target
    t = filtered(
        sims[(best.stop, target, order)], best.relvol, None if pd.isna(best.cutoff) else best.cutoff
    )
    acct = orb.Account(equity=cap, top_n=1, plan="tiered", slippage=None)
    eq, _ = orb.run_portfolio(
        t.assign(entry_slip=slip_in, exit_slip=slip_out), acct, calendars["all"]
    )
    dsr = A.deflated_sharpe(eq.pct_change().dropna(), N_CONFIGS, float(g["all daily SR"].var()))
    return {
        "scenario": scen,
        "account": f"${cap / 1000:.0f}k",
        "best config (full period)": label(best.stop, target, best.relvol, best.cutoff),
    } | dsr


def ablation(results: pd.DataFrame, scen: str, cap: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    g = results[(results["scenario"] == scen) & (results["capital"] == cap)].copy()
    g["key"] = [label(*v) for v in g[list(PARAMS)].itertuples(index=False)]
    cols = ["train Sharpe", "test Sharpe", "all Sharpe", "all CAGR", "all max DD", "all trades"]

    def row(**cfg):
        c = BASELINE | cfg
        return g[g["key"] == label(c["stop"], c["target"], c["relvol"], c["cutoff"])].iloc[0]

    grid = {"stop": STOPS, "target": TARGETS, "relvol": RELVOLS, "cutoff": CUTOFFS}
    ofat = [("baseline", row())]
    for p, values in grid.items():
        for v in values:
            if v != BASELINE[p] and not (v is None and BASELINE[p] is None):
                ofat.append((f"only {p} = {v if v is not None else 'none'}", row(**{p: v})))
    ok = g[g["train trades"] >= MIN_TRAIN_TRADES]
    best = ok.loc[ok["train Sharpe"].idxmax()]
    best_cfg = {
        p: (None if (p in ("target", "cutoff") and pd.isna(best[p])) else best[p]) for p in PARAMS
    }
    loo = [("best (train)", row(**best_cfg))]
    for p in PARAMS:
        if best_cfg[p] != BASELINE[p]:
            loo.append((f"best, but {p} back to baseline", row(**(best_cfg | {p: BASELINE[p]}))))
    to_df = lambda items: pd.DataFrame({k: r[cols] for k, r in items}).T  # noqa: E731
    return to_df(ofat), to_df(loo)


def heatmap(results: pd.DataFrame, scen: str, cap: float, value: str) -> pd.DataFrame:
    g = results[
        (results["scenario"] == scen)
        & (results["capital"] == cap)
        & (results["relvol"] == 1.0)
        & results["cutoff"].isna()
    ]
    g = g.assign(target=g["target"].map(lambda t: "hold" if pd.isna(t) else f"{t:g}R"))
    return g.pivot(index="stop", columns="target", values=value)[["hold", "1R", "2R", "3R", "5R"]]


# ---------------------------------------------------------------- report


def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if any(k in c for k in ("CAGR", "max DD", "beating", "win rate")):
            out[c] = out[c].map(lambda v: f"{v:.1%}" if pd.notna(v) else "-")
        elif pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].map(lambda v: f"{v:.2f}" if pd.notna(v) else "-")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--save", action="store_true", help="save baseline + best-train runs as bundles")
    args = p.parse_args()

    t0 = perf_counter()
    results, sims, calendars = run_grid(args.workers)
    out = REPO_ROOT / "data" / "results" / "orb_grid.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    results.assign(
        cutoff=results["cutoff"].map(lambda c: None if c is None else c.strftime("%H:%M"))
    ).to_parquet(out)
    print(f"{len(results):,} evaluated combinations in {perf_counter() - t0:.0f}s -> {out}\n")

    with pd.option_context(
        "display.width", 300, "display.max_columns", 40, "display.max_colwidth", 80
    ):
        print("=== best config chosen on TRAIN, judged on TEST ===")
        print(_fmt(summary(results)).to_string(index=False))
        print("\n=== deflated Sharpe of the best FULL-period config (480 trials each) ===")
        dsr = pd.DataFrame(
            [deflated(results, sims, calendars, s, c) for s in SCENARIOS for c in CAPITALS]
        )
        print(_fmt(dsr).to_string(index=False))
        for scen in ("measured, stop-limit", "1c"):
            ofat, loo = ablation(results, scen, 5_000.0)
            print(f"\n=== ablation, {scen}, $5k: one change from the baseline ===")
            print(_fmt(ofat).to_string())
            print(f"\n=== ablation, {scen}, $5k: best-train config minus one change ===")
            print(_fmt(loo).to_string())
        for value in ("train Sharpe", "test Sharpe"):
            print(f"\n=== {value}: stop x target (measured, stop-limit, $5k, any relvol/time) ===")
            print(heatmap(results, "measured, stop-limit", 5_000.0, value).round(2).to_string())

    if args.save:
        g = results[
            (results["scenario"] == "measured, stop-limit") & (results["capital"] == 5_000.0)
        ]
        ok = g[g["train trades"] >= MIN_TRAIN_TRADES]
        for name, row in (
            ("baseline", g[is_baseline(g)].iloc[0]),
            ("best on train", ok.loc[ok["train Sharpe"].idxmax()]),
        ):
            target = None if pd.isna(row.target) else row.target
            cutoff = None if pd.isna(row.cutoff) else row.cutoff
            t = filtered(sims[(row.stop, target, "limit")], row.relvol, cutoff).assign(
                entry_slip=0.0, exit_slip=0.04
            )
            acct = orb.Account(equity=5_000.0, top_n=1, plan="tiered", slippage=None)
            extra = {
                "caveats": [
                    *orb.ORB_CAVEATS,
                    f"Chosen from {N_CONFIGS} grid configs (orb_grid.py).",
                ]
            }
            print(
                "saved",
                orb.save_orb_run(
                    f"ORB grid {name}: {label(row.stop, target, row.relvol, cutoff)}",
                    t,
                    acct,
                    I.RULES,
                    extra,
                    calendars["all"],
                ),
            )


if __name__ == "__main__":
    main()
