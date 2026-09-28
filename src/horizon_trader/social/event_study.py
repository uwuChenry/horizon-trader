"""Does following Serenity (@aleabitoreddit) make money? An event study of every $cashtag.

    uv run python -m horizon_trader.social.event_study [--stance] [--save]

--save writes the follower portfolios as dashboard bundles, with the event table attached.
--stance adds the bullish / bearish / neutral labels from stance.py (see below).

Pre-registered (2026-09-27, before running):
  events     every $TICKER he cashtags in his own posts (archive.py), one event per ticker per
             entry day, treated as a LONG call (without --stance, see below). Tickers need
             Massive US bars; crypto symbols are dropped ($LTC would be LTC Properties).
  timing     the post time is the id's snowflake time (set by X, can't be backdated).
             His price: the last completed minute bar before the post (in session) or the
             last close (outside it). A follower's price: the open of the minute bar 1 / 5 /
             15 / 60 minutes after the post, in session; otherwise the next regular open.
  returns    from the 1-minute follower price to the close of the entry day and of 5, 20 and
             60 trading days later; minus SMH (semis ETF) and SPY bought at the same moment.
             Split-adjusted, price only.
  groups     all events, first mentions, and by liquidity at the time (21-day average dollar
             volume >= $1B, $100M-$1B, < $100M). t-stats cluster by entry week, since
             events in the same week share the same market move.
  portfolios $5k, IBKR Pro Tiered, 5 bps slippage, the daily book's simulator (signals known
             before an open trade at that open), each name 1/max(N, 10) of equity:
             A. first mention, held 60 trading days
             B. every ticker mentioned in the last 20 trading days
             C. every ticker he has mentioned so far
             (D, added AFTER seeing A-C, so not pre-registered: the 10 tickers mentioned
             on the most days in the last 20, i.e. his high-conviction names)
             vs SMH, SPY and QQQ held over the same days. Gross (no costs) shown too.
Stance (pre-registered 2026-09-27, before any label was seen): Claude labels every
(post, ticker) bullish / bearish / neutral from the text alone (stance.py). A day's stance on a
ticker is its last non-neutral label that day. Bullish = buy, bearish = sell if held, neutral =
nothing; long only, no shorts. Returns are reported by stance, and A-D get bullish versions:
             bA. first bullish call, held 60 days, sold early on a bearish call
             bB. bullish call in the last 20 days, and no bearish call since the latest one
             bC. held from a bullish call until a bearish one (no time limit)
             bD. top 10 by days with a bullish call in the last 20, among names held under bC
             Placebo: the same labels shuffled across events 50 times; the labels carry
             information only if the real result beats 95% of shuffles.
Known biases, all in his favour: deleted posts are missing, and the sample is 14 months of an
AI-hardware boom. Foreign listings he talks about most ($SIVE Sivers, $SOI Soitec, $IQE, $RPI,
$LPK) have no US bars and can't be tested here.
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.backtest import bundle
from horizon_trader.backtest import winners as W
from horizon_trader.backtest.sim import simulate
from horizon_trader.config import ExecutionSettings
from horizon_trader.data import massive, massive_ref
from horizon_trader.execution.costs import ZERO_COSTS, ibkr_costs
from horizon_trader.intraday import features as F
from horizon_trader.social import archive, stance

TZ = massive.TZ
BENCH = ("SMH", "SPY", "QQQ")
LAGS = (1, 5, 15, 60)  # minutes after the post
HORIZONS = (0, 5, 20, 60)  # trading-day closes after the entry day (0 = the entry day's close)
CRYPTO = set(
    "BTC ETH SOL LTC NEO XRP DOGE ADA HYPE BNB SUI AVAX LINK DOT TRX TON PEPE SHIB BCH XLM".split()
)
LIQUIDITY = [(1e9, ">= $1B/day"), (1e8, "$100M-$1B/day"), (0.0, "< $100M/day")]
CAPITAL = 5_000.0
MIN_SLOTS = 10  # each name gets 1/max(N, 10) of equity
HOLD = 60
RECENT = 20
PRICE_START = date(2025, 5, 1)  # a month before the first post, for dollar volume


# ---------------------------------------------------------------- prices


def load_prices(tickers: set[str]) -> dict:
    days = [d for d in massive.local_days("day") if d >= PRICE_START]
    panels = F.load_daily_panels(days, tickers | set(BENCH))
    factor = F.split_factors(
        panels["close"].index, panels["close"].columns, massive_ref.load_splits()
    )
    dollar_vol = (panels["close"] * panels["volume"]).rolling(21, min_periods=10).mean()
    return {
        "open": panels["open"],
        "close": panels["close"],
        "factor": factor,
        "adj": panels["close"] * factor,
        "adj_open": panels["open"] * factor,
        "dollar_vol": dollar_vol,
    }


def listing_start(adj: pd.DataFrame) -> pd.Series:
    """First date of the security trading under each ticker now (after its last gap of more
    than 30 days): a reused ticker (SPCX was a SPAC ETF before SpaceX) must not join two
    securities."""
    return pd.Series({t: s.index[0] for t in adj.columns if len(s := W.current_listing(adj[t]))})


# ---------------------------------------------------------------- timing


def signal_rows(ts: pd.Series, days: pd.DatetimeIndex) -> np.ndarray:
    """Index of the last trading day whose 9:30 open is at or before each post. A daily
    strategy acting on the post trades at the open of the NEXT day (row + 1), so nothing is
    used before it was posted: an in-session post waits a day, a pre-market post trades that
    morning, a weekend post trades Monday."""
    opens = pd.DatetimeIndex([F.session_open(d.date()) for d in days])
    return opens.searchsorted(pd.DatetimeIndex(ts), side="right") - 1


def in_session(ts: pd.Timestamp, day: pd.Timestamp) -> bool:
    return F.session_open(day.date()) <= ts < F.session_open(day.date()) + pd.Timedelta(hours=6.5)


def minute_prices(bars: pd.DataFrame, ts: pd.Timestamp, lags=LAGS) -> dict:
    """His price and the follower's, from one ticker's regular-session minute bars that day.
    `bars` has ts (bar start) and open/close. The bar containing the post isn't complete yet,
    so his price is the close of the last bar that started before the post's minute."""
    minute = ts.floor("min")
    before = bars[bars["ts"] < minute]
    out = {"ref": before["close"].iloc[-1] if len(before) else np.nan}
    for lag in lags:
        after = bars[bars["ts"] >= minute + pd.Timedelta(minutes=lag)]
        out[f"px_{lag}m"] = after["open"].iloc[0] if len(after) else np.nan
    return out


def build_calls(ments: pd.DataFrame, px: dict) -> pd.DataFrame:
    """Every testable mention with its signal row (see signal_rows) and entry day. The
    portfolios run on this table; the event study de-duplicates it (build_events)."""
    days = px["close"].index
    have = set(px["close"].columns)
    starts = listing_start(px["adj"])
    m = ments[ments["ticker"].isin(have - CRYPTO) & (ments["ts"] >= F.session_open(days[0].date()))]
    rows = []
    for r, row in zip(m.itertuples(), signal_rows(m["ts"], days), strict=True):
        same_day = in_session(r.ts, days[row])
        entry = row if same_day else row + 1
        if entry >= len(days) or days[entry] < starts.get(r.ticker, days[0]):
            continue
        rows.append(
            {
                "id": r.id,
                "ts": r.ts,
                "ticker": r.ticker,
                "row": row,
                "entry": entry,
                "in_session": same_day,
                "first_mention": r.first_mention,
                "stance": getattr(r, "stance", None),
            }
        )
    calls = pd.DataFrame(rows).sort_values("ts", ignore_index=True)
    return calls if "stance" in ments else calls.drop(columns="stance")


def build_events(calls: pd.DataFrame, px: dict) -> pd.DataFrame:
    """One row per (ticker, entry day), or per (ticker, entry day, stance) with labels: the
    first such post, his price, the follower's prices, and the benchmarks at the same moments."""
    key = ["ticker", "entry"] + (["stance"] if "stance" in calls else [])
    ev = calls.drop_duplicates(key, keep="first").reset_index(drop=True)
    if "stance" in calls:
        bull = ev["stance"] == "bullish"
        ev["first_bullish"] = bull & ~ev["ticker"].where(bull).duplicated()
    return _attach_prices(ev, px)


def _attach_prices(ev: pd.DataFrame, px: dict) -> pd.DataFrame:
    days = px["close"].index
    cols = ["ref", *(f"px_{lag}m" for lag in LAGS)]
    out = {b: pd.DataFrame(np.nan, index=ev.index, columns=cols) for b in ("", *BENCH)}
    for d, grp in ev[ev["in_session"]].groupby("entry"):
        day = days[d].date()
        start = F.session_open(day)
        window = [
            ("ticker", "in", sorted(set(grp["ticker"]) | set(BENCH))),
            ("ts", ">=", start),
            ("ts", "<", start + pd.Timedelta(hours=6.5)),
        ]
        bars = pd.read_parquet(massive.local_path("minute", day), filters=window)
        by = dict(tuple(bars.groupby("ticker")))
        empty = bars.iloc[:0]
        for i, r in grp.iterrows():
            out[""].loc[i] = minute_prices(by.get(r.ticker, empty), r.ts)
            for b in BENCH:
                out[b].loc[i] = minute_prices(by.get(b, empty), r.ts)
    ev = ev.copy()
    for b, frame in out.items():
        for c in cols:
            ev[f"{b}_{c}".lstrip("_")] = frame[c]
    # outside the session, or no bar before the close: his price is the last close, the
    # follower's is the next regular open; the entry day moves to that open
    missing = ~ev["in_session"] | ev["px_1m"].isna()
    ev.loc[missing & ev["in_session"], "entry"] += 1
    ev = ev[ev["entry"] < len(days)].copy()
    missing = missing.reindex(ev.index)
    for t in ("", *BENCH):
        tick = ev["ticker"] if t == "" else pd.Series(t, index=ev.index)
        pre = "" if t == "" else f"{t}_"
        prev = _lookup(px["close"], ev["entry"] - 1, tick)
        opn = _lookup(px["open"], ev["entry"], tick)
        ev[f"{pre}ref"] = ev[f"{pre}ref"].fillna(pd.Series(prev, index=ev.index))
        for lag in LAGS:
            ev[f"{pre}px_{lag}m"] = ev[f"{pre}px_{lag}m"].where(~missing, opn)
    ev["entry_mode"] = np.where(missing, "next open", "in session")
    ev["entry_date"] = days[ev["entry"]]
    ev["dollar_vol"] = _lookup(px["dollar_vol"], ev["row"], ev["ticker"])
    return ev.reset_index(drop=True)


def _lookup(panel: pd.DataFrame, rows: pd.Series, tickers: pd.Series) -> np.ndarray:
    ok = (rows >= 0) & (rows < len(panel)) & tickers.isin(panel.columns)
    out = np.full(len(rows), np.nan)
    r = rows[ok].to_numpy()
    c = panel.columns.get_indexer(tickers[ok])
    out[ok.to_numpy()] = panel.to_numpy()[r, c]
    return out


# ---------------------------------------------------------------- returns


def forward_returns(ev: pd.DataFrame, px: dict, horizons=HORIZONS) -> pd.DataFrame:
    """Return from the 1-minute follower price (and from his price) to later closes, for the
    stock and each benchmark bought at the same moment; plus excess over SMH and SPY."""
    ev = ev.copy()
    last = len(px["close"].index) - 1
    closes = px["adj"].ffill()  # a stock that stops trading is held at its last price
    for t in ("", *BENCH):
        tick = ev["ticker"] if t == "" else pd.Series(t, index=ev.index)
        pre = "" if t == "" else f"{t}_"
        f_entry = _lookup(px["factor"], ev["entry"], tick)
        f_ref = _lookup(px["factor"], ev["entry"] - (ev["entry_mode"] == "next open"), tick)
        for h in horizons:
            rows = ev["entry"] + h
            end = pd.Series(_lookup(closes, rows, tick), index=ev.index).where(rows <= last)
            ev[f"{pre}ret_{h}d"] = end / (ev[f"{pre}px_1m"] * f_entry) - 1
            if t == "":
                ev[f"ret_{h}d_from_his_price"] = end / (ev["ref"] * f_ref) - 1
    for h in horizons:
        for b in ("SMH", "SPY"):
            ev[f"xs_{b}_{h}d"] = ev[f"ret_{h}d"] - ev[f"{b}_ret_{h}d"]
    for lag in LAGS:
        ev[f"chase_{lag}m"] = ev[f"px_{lag}m"] / ev["ref"] - 1
    return ev


def liquidity_bucket(dollar_vol: pd.Series) -> pd.Series:
    out = pd.Series("unknown", index=dollar_vol.index)
    for floor, label in reversed(LIQUIDITY):
        out[dollar_vol >= floor] = label
    return out


def clustered_t(values: pd.Series, clusters: pd.Series) -> float:
    """t-stat of the mean, treating each cluster (entry week) as one observation."""
    means = values.groupby(clusters).mean().dropna()
    if len(means) < 3 or means.std() == 0:
        return np.nan
    return float(means.mean() / (means.std() / np.sqrt(len(means))))


def summarize(ev: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    week = ev["entry_date"].dt.to_period("W")
    bucket = liquidity_bucket(ev["dollar_vol"])
    if "stance" in ev:
        groups = {f"{st} calls": ev.index[ev["stance"] == st] for st in ("bullish", "bearish")}
        groups["neutral mentions"] = ev.index[ev["stance"] == "neutral"]
        groups["first bullish calls"] = ev.index[ev["first_bullish"]]
        for _, label in LIQUIDITY:
            groups[f"bullish, {label}"] = ev.index[(ev["stance"] == "bullish") & (bucket == label)]
    else:
        groups = {"all events": ev.index, "first mentions": ev.index[ev["first_mention"]]}
        for _, label in LIQUIDITY:
            groups[label] = ev.index[bucket == label]
    rows = []
    for name, idx in groups.items():
        for h in horizons:
            r = ev.loc[idx, f"ret_{h}d"].dropna()
            xs = ev.loc[r.index, f"xs_SMH_{h}d"]
            rows.append(
                {
                    "group": name,
                    "horizon": f"{h}d" if h else "entry day",
                    "events": len(r),
                    "mean": r.mean(),
                    "median": r.median(),
                    "% up": (r > 0).mean(),
                    "mean vs SMH": xs.mean(),
                    "median vs SMH": xs.median(),
                    "% beat SMH": (xs > 0).mean(),
                    "t vs SMH (weekly)": clustered_t(xs, week.loc[r.index]),
                    "mean vs SPY": ev.loc[r.index, f"xs_SPY_{h}d"].mean(),
                }
            )
    return pd.DataFrame(rows).set_index(["group", "horizon"])


def chase_table(ev: pd.DataFrame) -> pd.DataFrame:
    """How far the price had moved from his price by the time a follower could buy."""
    rows = []
    for mode, g in ev.groupby("entry_mode"):
        lags = LAGS if mode == "in session" else LAGS[:1]
        for lag in lags:
            c = g[f"chase_{lag}m"].dropna()
            label = f"+{lag} min" if mode == "in session" else "next open vs last close"
            rows.append(
                {
                    "posted": mode,
                    "follower buys": label,
                    "events": len(c),
                    "mean": c.mean(),
                    "median": c.median(),
                    "p90": c.quantile(0.9),
                }
            )
    return pd.DataFrame(rows).set_index(["posted", "follower buys"])


# ---------------------------------------------------------------- follower portfolios


def stance_signal(ev: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """+1 / -1 / 0 per (row, ticker): the day's last non-neutral call, 0 if none."""
    sig = pd.DataFrame(0.0, index=days, columns=sorted(ev["ticker"].unique()))
    calls = ev[ev["stance"] != "neutral"].sort_values("ts")
    for r in calls.itertuples():  # later posts overwrite earlier ones the same day
        sig.iat[r.row, sig.columns.get_loc(r.ticker)] = 1.0 if r.stance == "bullish" else -1.0
    return sig


def bullish_held(ev: pd.DataFrame, days: pd.DatetimeIndex, variant: str) -> pd.DataFrame:
    """Which names the long-only stance rules hold on each row (see the module docstring)."""
    sig = stance_signal(ev, days)
    long_since = sig.replace(0.0, np.nan).ffill().fillna(0.0) == 1.0  # bC
    bull = (sig == 1.0).astype(int)
    if variant == "bC":
        return long_since
    if variant == "bB":
        return long_since & (bull.rolling(RECENT, min_periods=1).max() > 0)
    if variant == "bD":  # most bullish days, then A-Z
        count = bull.rolling(RECENT, min_periods=1).sum()
        count = count.where(long_since & (count > 0))
        return count.rank(axis=1, method="first", ascending=False) <= MIN_SLOTS
    # bA: first bullish call, HOLD days, cut short by a bearish call
    pos = pd.DataFrame(
        np.arange(len(days))[:, None].repeat(sig.shape[1], axis=1), index=days, columns=sig.columns
    )
    first = (sig == 1.0).idxmax().map(days.get_loc).where((sig == 1.0).any())
    after = pos.ge(first, axis=1)
    bear_since = ((sig == -1.0) & after).astype(int).cummax().astype(bool)
    return after & pos.lt(first + HOLD, axis=1) & ~bear_since


def targets(ev: pd.DataFrame, days: pd.DatetimeIndex, variant: str) -> pd.DataFrame:
    """Daily target weights, row t = what's known before the open of t + 1 (the simulator
    trades row t at the next open). Each held name gets 1 / max(N, MIN_SLOTS)."""
    names = sorted(ev["ticker"].unique())
    held = pd.DataFrame(False, index=days, columns=names)
    if variant.startswith("b"):
        held = bullish_held(ev, days, variant)
    elif variant == "A":  # first mention, held HOLD days
        for r in ev[ev["first_mention"]].itertuples():
            held.iloc[r.row : r.row + HOLD, held.columns.get_loc(r.ticker)] = True
    else:
        hit = pd.DataFrame(False, index=days, columns=names)
        for r in ev.itertuples():
            hit.iat[r.row, hit.columns.get_loc(r.ticker)] = True
        window = len(days) if variant == "C" else RECENT
        days_hit = hit.astype(int).rolling(window, min_periods=1).sum()
        held = days_hit > 0
        if variant == "D":  # his 10 most-talked-about names: most days mentioned, then A-Z
            rank = days_hit.where(held).rank(axis=1, method="first", ascending=False)
            held = rank <= MIN_SLOTS
    n = held.sum(axis=1).clip(lower=MIN_SLOTS)
    return held.astype(float).div(n, axis=0)


def run_follower(ev: pd.DataFrame, px: dict, variant: str, costs) -> tuple[pd.Series, pd.DataFrame]:
    days = px["close"].index
    tgt = targets(ev, days, variant)
    first = tgt.index[tgt.sum(axis=1) > 0][0]
    tgt = tgt.loc[first:]
    res = simulate(
        tgt,
        px["adj_open"].loc[first:, tgt.columns],
        px["adj"].loc[first:, tgt.columns],
        CAPITAL,
        ExecutionSettings(),
        costs,
    )
    return res.equity, res.trades


VARIANTS = {
    "A": "first mention, held 60 days",
    "B": "mentioned in the last 20 days",
    "C": "everything mentioned so far",
    "D": "top 10 by days mentioned in the last 20 (added after seeing A-C)",
}
BULL_VARIANTS = {
    "bA": "first bullish call, held 60 days, sold on a bearish call",
    "bB": "bullish call in the last 20 days, no bearish since",
    "bC": "held from a bullish call until a bearish one",
    "bD": "top 10 by bullish days in the last 20",
}


def portfolio_table(calls: pd.DataFrame, px: dict, variants: dict) -> tuple[pd.DataFrame, dict]:
    rows, curves = [], {}
    adj = px["adj"]
    for v, label in variants.items():
        net, fills = run_follower(calls, px, v, ibkr_costs("tiered", 5.0))
        gross, _ = run_follower(calls, px, v, ZERO_COSTS)
        curves[v] = (net, fills)
        smh = adj["SMH"].reindex(net.index)
        for kind, eq in (("$5k net", net), ("gross", gross)):
            s = A.equity_stats(eq, smh)
            rows.append(
                {
                    "portfolio": f"{v}. {label}",
                    "costs": kind,
                    "from": eq.index[0].date(),
                    "CAGR": s["CAGR"],
                    "total": s["total return"],
                    "Sharpe": s["Sharpe"],
                    "max DD": s["max DD"],
                    "beta to SMH": s.get("beta"),
                    "alpha/yr vs SMH": s.get("alpha/yr"),
                    "costs $": fills["commission"].sum() if kind == "$5k net" else 0.0,
                    "trades": len(fills) if kind == "$5k net" else np.nan,
                }
            )
    start = min(eq.index[0] for eq, _ in curves.values())
    for b in BENCH:
        eq = adj[b].loc[start:].dropna()
        s = A.equity_stats(eq / eq.iloc[0], adj["SMH"].loc[start:])
        rows.append(
            {
                "portfolio": f"benchmark: {b} buy and hold",
                "costs": "gross",
                "from": start.date(),
                "CAGR": s["CAGR"],
                "total": s["total return"],
                "Sharpe": s["Sharpe"],
                "max DD": s["max DD"],
                "beta to SMH": s.get("beta"),
                "alpha/yr vs SMH": s.get("alpha/yr"),
            }
        )
    return pd.DataFrame(rows).set_index(["portfolio", "costs"]), curves


def shuffle_stance(calls: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """The same mentions and label counts, with the labels dealt out at random. Shuffled per
    mention, not per de-duplicated event: a much-discussed ticker has several mentions a day,
    and shuffling events would give it fewer labels than the real data does."""
    return calls.assign(stance=rng.permutation(calls["stance"].to_numpy()))


def placebo_table(calls: pd.DataFrame, px: dict, n: int, seed: int = 0) -> pd.DataFrame:
    """Do the labels carry information? The bullish rules' net Sharpe and CAGR with the real
    labels vs `n` shuffles of them. Pass (pre-registered): the real value beats 95% of
    shuffles."""
    rng = np.random.default_rng(seed)
    costs = ibkr_costs("tiered", 5.0)

    def measure(e: pd.DataFrame) -> dict:
        out = {}
        for v in BULL_VARIANTS:
            eq, _ = run_follower(e, px, v, costs)
            s = A.equity_stats(eq)
            out[f"{v} Sharpe"], out[f"{v} CAGR"] = s["Sharpe"], s["CAGR"]
        return out

    real = measure(calls)
    fakes = pd.DataFrame([measure(shuffle_stance(calls, rng)) for _ in range(n)])
    rows = [
        {
            "measure": k,
            "real labels": v,
            "shuffled median": fakes[k].median(),
            "shuffled 95th pct": fakes[k].quantile(0.95),
            "share of shuffles >= real": (fakes[k] >= v).mean(),
        }
        for k, v in real.items()
    ]
    return pd.DataFrame(rows).set_index("measure")


# ---------------------------------------------------------------- report


def _pct(df: pd.DataFrame, cols) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c] = out[c].map(lambda v: "-" if pd.isna(v) else f"{v:+.1%}")
    return out


def coverage(ments: pd.DataFrame, ev: pd.DataFrame, px: dict) -> str:
    have = set(px["close"].columns) - CRYPTO
    n = ments.groupby("ticker").size().sort_values(ascending=False)
    lost = n[~n.index.isin(have)]
    return (
        f"mentions: {len(ments):,} of {n.size} tickers; {n[n.index.isin(have)].sum() / n.sum():.0%}"
        f" are US-listed with Massive bars -> {len(ev):,} events (one per ticker per entry day)\n"
        f"not testable (no US bars or crypto), most mentioned: "
        + ", ".join(f"{t} ({k})" for t, k in lost.head(10).items())
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--save", action="store_true", help="save the follower portfolios as runs")
    p.add_argument("--stance", action="store_true", help="use the bullish/bearish/neutral labels")
    p.add_argument("--placebo", type=int, default=50, help="label shuffles with --stance")
    args = p.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)

    _, ments = archive.load()
    variants = VARIANTS
    if args.stance:
        labels = stance.load()
        n = len(ments)
        ments = ments.merge(labels, on=["id", "ticker"], how="inner")
        print(
            f"stance labels: {len(ments):,} of {n:,} mentions labelled "
            f"({ments['stance'].value_counts().to_dict()})"
        )
        variants = VARIANTS | BULL_VARIANTS
    px = load_prices(set(ments["ticker"]))
    calls = build_calls(ments, px)
    ev = forward_returns(build_events(calls, px), px)
    print(coverage(ments, ev, px))
    print(
        f"prices through {px['close'].index[-1].date()}; "
        f"posts {ev['ts'].min():%Y-%m-%d} .. {ev['ts'].max():%Y-%m-%d}\n"
    )

    print("=== chasing: how far the price moved from his price before a follower could buy ===")
    print(_pct(chase_table(ev), ["mean", "median", "p90"]).to_string())

    print("\n=== forward returns from the follower's price (1 minute after the post) ===")
    s = summarize(ev)
    pct_cols = [
        "mean",
        "median",
        "% up",
        "mean vs SMH",
        "median vs SMH",
        "% beat SMH",
        "mean vs SPY",
    ]
    fmt = _pct(s, pct_cols)
    fmt["t vs SMH (weekly)"] = s["t vs SMH (weekly)"].map(lambda v: f"{v:.2f}")
    print(fmt.to_string())

    print("\n=== his price vs the follower's: mean 20-day return ===")
    both = ev[["ret_20d_from_his_price", "ret_20d"]].dropna()
    print(
        f"from his price {both.iloc[:, 0].mean():+.1%}, from 1 minute later "
        f"{both.iloc[:, 1].mean():+.1%} ({len(both)} events)"
    )

    print("\n=== follower portfolios ===")
    table, curves = portfolio_table(calls, px, variants)
    fmt = _pct(table, ["CAGR", "total", "max DD", "alpha/yr vs SMH"])
    for c in ("Sharpe", "beta to SMH"):
        fmt[c] = table[c].map(lambda v: "-" if pd.isna(v) else f"{v:.2f}")
    fmt["costs $"] = table["costs $"].map(lambda v: "-" if pd.isna(v) else f"{v:,.0f}")
    print(fmt.to_string())

    if args.stance and args.placebo:
        print(f"\n=== placebo: real labels vs {args.placebo} random shuffles of them ===")
        pl = placebo_table(calls, px, args.placebo)
        print(pl.map(lambda v: f"{v:.3f}").to_string())

    first = "first_bullish" if args.stance else "first_mention"
    fm = ev[ev[first]].dropna(subset=["ret_60d"])
    print(f"\n=== {first.replace('_', ' ')}: the 10 best and 10 worst 60-day results ===")
    show = ["ts", "ticker", "entry_mode", "ret_60d", "xs_SMH_60d"]
    print(fm.nlargest(10, "ret_60d")[show].to_string(index=False))
    print(fm.nsmallest(10, "ret_60d")[show].to_string(index=False))

    if args.save:
        marks = px["adj"].ffill().iloc[-1].dropna().to_dict()
        for v, (eq, fills) in curves.items():
            if args.stance and v in VARIANTS:  # saved already by the run without --stance
                continue
            meta = {
                "strategy": "follow Serenity (@aleabitoreddit) cashtags",
                "params": {"variant": variants[v], "capital": CAPITAL, "min_slots": MIN_SLOTS},
                "chart": "daily",
                "caveats": [
                    "Stance labelled by Claude from the text; may leak hindsight."
                    if args.stance
                    else "Every cashtag treated as a long call (no stance extraction yet).",
                    "Deleted posts missing from the archive: biased in his favour.",
                    "14 months of an AI-hardware boom; foreign listings not testable.",
                    "Pre-registered variants in social/event_study.py (D was added later).",
                ],
                "benchmark": "SMH (price only)",
            }
            tables = {
                "holdings": W.holdings_history(fills, px["adj"], eq),
                "events": ev.drop(columns=["row", "entry"]),
            }
            trips = A.round_trips(fills, marks)
            path = bundle.save_run(
                f"serenity: {variants[v]}, $5k net",
                eq,
                trips,
                meta,
                px["adj"]["SMH"].reindex(eq.index).ffill(),
                tables,
            )
            print("saved", path.name)


if __name__ == "__main__":
    main()
