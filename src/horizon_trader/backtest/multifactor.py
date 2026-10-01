"""Multi-factor stock selection among the 200 largest US companies (point-in-time).

    uv run python -m horizon_trader.datasources.sec download  # first: SEC fundamentals + 10-K text
    uv run python -m horizon_trader.backtest.multifactor [--save]

Pre-registered (2026-09-29, before any result was seen; write-up in research/multifactor.md):
  universe   each month-end, the 200 largest US companies by market cap on that date
             (Massive point-in-time caps, delisted included, one share class each), as in
             backtest/winners.py
  signals    all scored so higher = better, each known at the formation close:
             momentum   12-1 month return (Jegadeesh & Titman 1993)
             value      average of book-to-market and earnings yield (equity and net income
                        from the latest ORIGINAL 10-K filed before the date / market cap)
             quality    gross profits / total assets (Novy-Marx 2013); banks have none
             low_vol    minus the 1-year volatility of daily returns
             lazy       cosine similarity of the latest 10-K's words to the previous 10-K's
                        (Cohen, Malloy & Nguyen 2020, "Lazy Prices": firms that change their
                        10-K a lot underperform, so high similarity = good)
  combining  each signal is turned into a cross-sectional rank z-score on each date; the
             composite is the plain average of the available z-scores (at least 3 required).
             Equal weights, fixed in advance: no weight is fitted to returns.
  learned    "ridge": weights learned by ridge regression of next month's return rank on the
             five z-scores, walk-forward (trained only on months whose returns were known at
             the formation date, expanding window, starts after 12 months of training data,
             penalty = number of rows). This answers "why not let a model learn the weights".
  portfolio  top 20 by score, equal weight, formed at the month-end close, traded at the next
             open; $5k IBKR Pro Tiered, 5 bps slippage, 2% band (the winners.py simulator),
             and gross (no costs)
  benchmark  the same 200 companies equal weight (the project rule), plus SPY
  pass rules 1. PRIMARY: the 4-signal composite (no text) beats the equal-weight universe on
                $5k net Sharpe over the whole test AND in each half.
             2. Lazy Prices adds value: the 5-signal composite beats the 4-signal one, whole
                test and both halves.
             3. Learned weights help: ridge beats the 5-signal equal-weight composite on the
                ridge's own window, whole and both halves.
  diagnostics each signal alone (top 20), rank IC per signal, signal correlations.
Price only (no dividends), like winners.py. About 4 years of test data in one market regime:
the standard error of a Sharpe ratio over 4 years is ~0.5, so small differences are noise.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.backtest import bundle
from horizon_trader.backtest import megacap as M
from horizon_trader.backtest import winners as W
from horizon_trader.datasources import sec

UNIVERSE = 200
TOP = 20
MIN_SIGNALS = 3
MIN_NAMES = 30  # a signal with fewer names on a date is treated as unavailable that date
TRAIN_MIN_MONTHS = 12
VOL_WINDOW = 252
MAX_FILING_AGE = 550  # days from fiscal year end: older 10-K data counts as missing
CORE = ["momentum", "value", "quality", "low_vol"]
ALL = [*CORE, "lazy"]


# ---------- signals ----------


def zscore(s: pd.Series) -> pd.Series:
    """Cross-sectional rank z-score: robust to outliers, NaN stays NaN."""
    ok = s.dropna()
    if len(ok) < MIN_NAMES:
        return pd.Series(np.nan, index=s.index)
    r = ok.rank(pct=True)
    return ((r - r.mean()) / r.std(ddof=0)).reindex(s.index)


def price_signals(adj: pd.DataFrame, max_missing: int = W.MAX_MISSING) -> dict[str, pd.DataFrame]:
    """Momentum and low volatility panels; row t uses prices up to t only."""
    rets = adj.pct_change(fill_method=None)
    vol = rets.rolling(VOL_WINDOW, min_periods=VOL_WINDOW - max_missing).std()
    missing = adj.isna().rolling(VOL_WINDOW).sum()
    return {
        "momentum": W.momentum(adj, 252, 21, max_missing),
        "low_vol": -vol.where(missing <= max_missing),
    }


def latest_filing(table: pd.DataFrame, d: pd.Timestamp, age_col: str) -> pd.DataFrame:
    """Each company's latest row filed strictly before d (not later that day: the filing may
    have landed after the close), dropped if `age_col` is more than MAX_FILING_AGE days old."""
    known = table[(table["filed"] < d) & (table[age_col] >= d - pd.Timedelta(MAX_FILING_AGE, "D"))]
    return known.sort_values("filed").groupby("cik").tail(1).set_index("cik")


def fundamental_signals(
    caps_d: pd.DataFrame, fund: pd.DataFrame, sims: pd.DataFrame, d: pd.Timestamp
) -> pd.DataFrame:
    """Raw value inputs, quality and lazy for the tickers in caps_d (ticker, cik, market_cap)."""
    cik = caps_d["cik"].map(lambda c: sec._cik10(c) if str(c).strip().isdigit() else None)
    f = latest_filing(fund, d, "period_end").reindex(cik.to_numpy())
    s = latest_filing(sims.assign(age=sims["filed"]), d, "age").reindex(cik.to_numpy())
    mcap = caps_d["market_cap"].to_numpy()
    out = pd.DataFrame(
        {
            "bm": f["equity"].to_numpy() / mcap,
            "ep": f["net_income"].to_numpy() / mcap,
            "quality": (f["gross_profit"] / f["assets"]).to_numpy(),
            "lazy": s["sim"].to_numpy(),
        },
        index=caps_d.index,
    )
    return out


def signal_table(data: dict, fund: pd.DataFrame, sims: pd.DataFrame) -> pd.DataFrame:
    """Long table: (date, ticker) -> z-scores of ALL signals + next month's return (`fwd`)."""
    px = price_signals(data["adj"])
    ends = data["ends"]
    rows = []
    for i, d in enumerate(ends):
        caps_d = data["caps"][data["caps"]["date"] == d].drop_duplicates("ticker")
        uni = W.point_in_time_universe(data, d)
        caps_d = caps_d.set_index("ticker").loc[uni]
        raw = fundamental_signals(caps_d, fund, sims, d)
        z = pd.DataFrame(index=uni)
        z["momentum"] = zscore(px["momentum"].loc[d].reindex(uni))
        z["low_vol"] = zscore(px["low_vol"].loc[d].reindex(uni))
        z["value"] = zscore(pd.concat([zscore(raw["bm"]), zscore(raw["ep"])], axis=1).mean(axis=1))
        z["quality"] = zscore(raw["quality"])
        z["lazy"] = zscore(raw["lazy"])
        nxt = ends[i + 1] if i + 1 < len(ends) else None
        z["fwd"] = (
            data["adj"].loc[nxt, uni] / data["adj"].loc[d, uni] - 1 if nxt is not None else np.nan
        )
        rows.append(z.assign(date=d))
    t = pd.concat(rows).rename_axis("ticker").reset_index()
    return t.set_index(["date", "ticker"])[[*ALL, "fwd"]]


def composite(table: pd.DataFrame, signals: list[str], min_signals: int = MIN_SIGNALS):
    z = table[signals]
    return z.mean(axis=1).where(z.notna().sum(axis=1) >= min_signals)


def ridge_scores(
    table: pd.DataFrame, signals: list[str] = ALL, min_months: int = TRAIN_MIN_MONTHS
) -> tuple[pd.Series, pd.DataFrame]:
    """Walk-forward ridge. At formation date k the model is fitted on dates j < k only (the
    return from date j to j+1 is known by date k). Returns (scores, weights by date)."""
    dates = table.index.get_level_values("date").unique().sort_values()
    X_all = table[signals].fillna(0.0)
    eligible = table[signals].notna().sum(axis=1) >= MIN_SIGNALS
    y_all = table["fwd"].groupby(level="date").rank(pct=True) - 0.5
    scores, weights = [], {}
    for k, d in enumerate(dates):
        train_dates = dates[:k]
        if len(train_dates) < min_months:
            continue
        mask = table.index.get_level_values("date").isin(train_dates) & eligible & y_all.notna()
        X, y = X_all[mask].to_numpy(), y_all[mask].to_numpy()
        w = np.linalg.solve(X.T @ X + len(X) * np.eye(X.shape[1]), X.T @ y)
        weights[d] = pd.Series(w, index=signals)
        today = X_all.loc[d]
        scores.append(pd.Series(today.to_numpy() @ w, index=today.index).where(eligible.loc[d]))
    s = pd.concat({d: sc for d, sc in zip(weights, scores, strict=True)}, names=["date", "ticker"])
    return s, pd.DataFrame(weights).T


def schedule_from(score: pd.Series, n: int = TOP) -> dict[pd.Timestamp, pd.Series]:
    out = {}
    for d, s in score.dropna().groupby(level="date"):
        s = s.droplevel("date")
        if len(s) >= 2 * n:
            out[d] = pd.Series(1.0, index=s.nlargest(n).index)
    return out


# ---------- evaluation ----------


def rank_ic(score: pd.Series, fwd: pd.Series) -> pd.Series:
    """Monthly Spearman correlation between a score and next month's return."""
    df = pd.DataFrame({"s": score, "f": fwd}).dropna()
    return df.groupby(level="date").apply(
        lambda g: g["s"].rank().corr(g["f"].rank()) if len(g) >= MIN_NAMES else np.nan
    )


def ic_summary(ic: pd.Series) -> dict:
    ic = ic.dropna()
    return {
        "months": len(ic),
        "mean IC": ic.mean(),
        "t": ic.mean() / ic.std() * np.sqrt(len(ic)) if len(ic) > 2 else np.nan,
        "% months > 0": (ic > 0).mean(),
    }


def _sharpe(eq: pd.Series) -> float:
    r = eq.pct_change().dropna()
    return float(r.mean() / r.std() * np.sqrt(252)) if r.std() else np.nan


def halves(eq: pd.Series, mid: pd.Timestamp) -> tuple[float, float]:
    return _sharpe(eq[eq.index <= mid]), _sharpe(eq[eq.index >= mid])


def evaluate(data: dict, sched: dict, start: pd.Timestamp, mid: pd.Timestamp) -> dict:
    """Gross and $5k net stats of a schedule restricted to formations from `start`."""
    sched = {d: w for d, w in sched.items() if d >= start}
    gross = M.run_portfolio(data["returns"], sched)
    net, trades = W.net_equity(data, sched)
    spy = data["adj"]["SPY"][data["adj"].index >= start].dropna()
    g, n = A.equity_stats(gross, spy), A.equity_stats(net, spy)
    h1, h2 = halves(net, mid)
    years = (net.index[-1] - net.index[0]).days / 365.25
    return {
        "gross CAGR": g["CAGR"],
        "gross Sharpe": g["Sharpe"],
        "net CAGR": n["CAGR"],
        "net Sharpe": n["Sharpe"],
        "max DD": n["max DD"],
        "beta": n.get("beta"),
        "Sharpe 1st half": h1,
        "Sharpe 2nd half": h2,
        "costs $": trades["commission"].sum() if len(trades) else 0.0,
        "trades/yr": len(trades) / years,
        "_net": net,
        "_trades": trades,
    }


def benchmark(eq: pd.Series, spy: pd.Series, mid: pd.Timestamp) -> dict:
    """Gross-only row. The 200-name equal-weight universe can't be held with $5k ($25 a name,
    at the simulator's dust threshold), so benchmarks are judged before costs, which is the
    stricter comparison for strategies that pay them."""
    s = A.equity_stats(eq, spy)
    h1, h2 = halves(eq, mid)
    return {
        "gross CAGR": s["CAGR"],
        "gross Sharpe": s["Sharpe"],
        "max DD": s["max DD"],
        "beta": s.get("beta"),
        "Sharpe 1st half": h1,
        "Sharpe 2nd half": h2,
    }


def universe_row(data: dict, start: pd.Timestamp, mid: pd.Timestamp) -> dict:
    sched = W.universe_schedule(data, [d for d in data["ends"] if d >= start])
    spy = data["adj"]["SPY"][data["adj"].index >= start].dropna()
    return benchmark(M.run_portfolio(data["returns"], sched), spy, mid)


def spy_row(data: dict, start: pd.Timestamp, mid: pd.Timestamp) -> dict:
    spy = data["adj"]["SPY"][data["adj"].index >= start].dropna()
    return benchmark(spy / spy.iloc[0], spy, mid)


def _beats(a: dict, b: dict) -> bool:
    """a's $5k net Sharpe beats b's (b's gross Sharpe for a benchmark), whole and both halves."""
    b_whole = b["net Sharpe"] if "net Sharpe" in b else b["gross Sharpe"]
    return (
        a["net Sharpe"] > b_whole
        and a["Sharpe 1st half"] > b["Sharpe 1st half"]
        and a["Sharpe 2nd half"] > b["Sharpe 2nd half"]
    )


def _fmt(table: pd.DataFrame) -> str:
    out = table.drop(columns=[c for c in table.columns if c.startswith("_")]).copy()
    for c in out.columns:
        pct = any(k in c for k in ("CAGR", "DD", "%"))
        out[c] = out[c].map(
            lambda v, p=pct: "-" if pd.isna(v) else (f"{v:.1%}" if p else f"{v:,.2f}")
        )
    return out.to_string()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--save", action="store_true", help="save the $5k net curves for the dashboard")
    args = p.parse_args()
    pd.set_option("display.width", 250)

    data = M.pit_data()
    ciks = sec.universe_ciks()
    fund = sec.fundamentals_panel(ciks)
    sims = pd.concat([sec.similarity_table(c) for c in ciks], ignore_index=True)
    table = signal_table(data, fund, sims)

    print("=== coverage: average names per month with each signal (of 200) ===")
    cov = table[ALL].notna().groupby(level="date").sum()
    print(cov[cov.index >= cov.index[12]].mean().round(0).to_string())

    scores = {f"{s} alone": table[s] for s in ALL}
    scores["composite 4 (no text)"] = composite(table, CORE)
    scores["composite 5 (+ lazy)"] = composite(table, ALL)
    ridge, ridge_w = ridge_scores(table)
    scores["ridge (learned weights)"] = ridge

    print("\n=== rank IC: correlation of each score with next month's return, per month ===")
    ic_rows = {k: ic_summary(rank_ic(v, table["fwd"])) for k, v in scores.items()}
    ic = pd.DataFrame(ic_rows).T
    ic["mean IC"] = ic["mean IC"].map("{:+.3f}".format)
    ic["t"] = ic["t"].map("{:+.2f}".format)
    ic["% months > 0"] = ic["% months > 0"].map("{:.0%}".format)
    print(ic.to_string())

    print("\n=== correlation between signals (pooled z-scores) ===")
    print(table[ALL].corr().round(2).to_string())

    sched = {k: schedule_from(v) for k, v in scores.items()}
    start = min(sched["composite 4 (no text)"])
    end = data["adj"].index[-1]
    mid = start + (end - start) / 2
    fixed = {k: v for k, v in sched.items() if k != "ridge (learned weights)"}
    rows = {k: evaluate(data, s, start, mid) for k, s in fixed.items()}
    rows["benchmark: 200 largest, equal weight"] = universe_row(data, start, mid)
    rows["benchmark: SPY"] = spy_row(data, start, mid)
    last = max(sched["composite 4 (no text)"]).date()
    print(f"\n=== top {TOP}, formations {start.date()} to {last} (halves split {mid.date()}), "
          "price only ===")  # fmt: skip
    print("(strategies: halves and max DD are $5k net; benchmarks: gross, no costs)")
    print(_fmt(pd.DataFrame(rows).T))

    r_start = min(sched["ridge (learned weights)"])
    r_mid = r_start + (end - r_start) / 2
    same = {
        "ridge (learned weights)": evaluate(data, sched["ridge (learned weights)"], r_start, r_mid),
        "composite 5 (+ lazy)": evaluate(data, sched["composite 5 (+ lazy)"], r_start, r_mid),
        "composite 4 (no text)": evaluate(data, sched["composite 4 (no text)"], r_start, r_mid),
        "benchmark: 200 largest, equal weight": universe_row(data, r_start, r_mid),
    }
    print(f"\n=== learned vs equal weights on the ridge's window ({r_start.date()} on) ===")
    print(_fmt(pd.DataFrame(same).T))
    print("\nridge weights (share of total |weight|), every 6th formation:")
    shares = ridge_w.div(ridge_w.abs().sum(axis=1), axis=0)
    print(shares.iloc[::6].map("{:+.2f}".format).to_string())

    uni = rows["benchmark: 200 largest, equal weight"]
    c4, c5 = rows["composite 4 (no text)"], rows["composite 5 (+ lazy)"]
    print("\n=== pre-registered verdicts ===")
    print(f"1. composite 4 beats the equal-weight universe (net, whole + both halves): "
          f"{'PASS' if _beats(c4, uni) else 'FAIL'}")  # fmt: skip
    print(f"2. adding Lazy Prices helps (composite 5 vs 4): {'PASS' if _beats(c5, c4) else 'FAIL'}")
    ridge_ok = _beats(same["ridge (learned weights)"], same["composite 5 (+ lazy)"])
    print(
        f"3. learned weights beat equal weights (ridge vs composite 5): "
        f"{'PASS' if ridge_ok else 'FAIL'}"
    )

    if args.save:
        adj = data["adj"]
        marks = adj.ffill().iloc[-1].dropna().to_dict()
        for name in ("composite 4 (no text)", "composite 5 (+ lazy)"):
            r = rows[name]
            eq, fills = r["_net"], r["_trades"]
            meta = {
                "strategy": "multi-factor large caps (point-in-time)",
                "params": {
                    "signals": CORE if "4" in name else ALL,
                    "top": TOP,
                    "capital": W.CAPITAL,
                },
                "oos_start": str(mid.date()),
                "chart": "daily",
                "caveats": [
                    "Price only (no dividends).",
                    "About 4 years of test data, one market regime.",
                    "Pre-registered variants in backtest/multifactor.py.",
                ],
                "benchmark": "SPY (price only)",
            }
            spy = adj["SPY"].reindex(eq.index).ffill()
            tables = {"holdings": W.holdings_history(fills, adj, eq)}
            path = bundle.save_run(
                f"multifactor: {name}, $5k net", eq, A.round_trips(fills, marks), meta, spy, tables
            )
            print("saved", path.name)


if __name__ == "__main__":
    main()
