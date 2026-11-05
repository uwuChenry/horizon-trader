"""Data shaping for the Holdings view (pure functions, so they're testable).

Input tables come from result bundles (`bundle.Run.tables`):
    holdings  one row per (date, ticker) held: shares, price, value, weight (of equity)
    picks     optional; each formation's ranking: formation, rank, ticker, name, momentum,
              market_cap, selected
"""

from __future__ import annotations

import pandas as pd


def snap(calendar: pd.DatetimeIndex, t) -> pd.Timestamp:
    """The last trading day on or before t (the first one if t is earlier)."""
    i = calendar.searchsorted(pd.Timestamp(t), side="right") - 1
    return calendar[max(i, 0)]


def held_matrix(holdings: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """date x ticker booleans: held at that close."""
    h = holdings.assign(held=True).pivot_table(
        index="date", columns="ticker", values="held", aggfunc="any"
    )
    return h.reindex(calendar).fillna(False).astype(bool)


def entry_dates(held: pd.DataFrame) -> pd.DataFrame:
    """date x ticker: the first day of the current continuous holding (NaT when not held)."""
    starts = held & ~held.shift(fill_value=False)
    days = pd.DataFrame({c: held.index for c in held.columns}, index=held.index)
    return days.where(starts).ffill().where(held)


def holding_periods(held: pd.DataFrame) -> pd.DataFrame:
    """One row per continuous holding: ticker, start, end (last day held)."""
    rows = []
    idx = held.index
    for t in held.columns:
        h = held[t].to_numpy()
        i = 0
        while i < len(h):
            if h[i]:
                j = i
                while j + 1 < len(h) and h[j + 1]:
                    j += 1
                rows.append({"ticker": t, "start": idx[i], "end": idx[j]})
                i = j + 1
            else:
                i += 1
    return pd.DataFrame(rows, columns=["ticker", "start", "end"])


def formation_for(picks: pd.DataFrame, t: pd.Timestamp) -> pd.Timestamp | None:
    """The formation whose portfolio is held at the close of t: formed at a month-end close and
    traded at the next open, so the formation must be strictly before t."""
    f = picks.loc[picks["formation"] < t, "formation"]
    return f.max() if len(f) else None


def rebalance_changes(picks: pd.DataFrame, f: pd.Timestamp) -> dict[str, list[str]]:
    """Bought / sold / kept at formation f vs the previous formation."""
    sel = picks[picks["selected"]]
    now = set(sel.loc[sel["formation"] == f, "ticker"])
    prev_f = sel.loc[sel["formation"] < f, "formation"]
    before = set(sel.loc[sel["formation"] == prev_f.max(), "ticker"]) if len(prev_f) else set()
    return {
        "bought": sorted(now - before),
        "sold": sorted(before - now),
        "kept": sorted(now & before),
    }


def positions_at(
    holdings: pd.DataFrame,
    equity: pd.Series,
    t: pd.Timestamp,
    picks: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """The portfolio at the close of t, biggest first, with entry date, the move since then
    and (if picks are given) the name, rank and momentum at the formation being held."""
    cal = equity.index
    held = held_matrix(holdings, cal)
    entry = entry_dates(held)
    pos = holdings[holdings["date"] == t].set_index("ticker")
    if pos.empty:
        return pd.DataFrame(
            columns=["name", "weight", "value", "shares", "price", "held since",
                     "trading days held", "move since bought", "rank", "momentum"]
        )  # fmt: skip
    px_wide = holdings.pivot_table(index="date", columns="ticker", values="price")
    out = pd.DataFrame(index=pos.index)
    out["weight"] = pos["weight"]
    out["value"] = pos["value"]
    out["shares"] = pos["shares"]
    out["price"] = pos["price"]
    since = entry.loc[t, pos.index]
    out["held since"] = since
    pos_of = {d: i for i, d in enumerate(cal)}
    out["trading days held"] = [pos_of[t] - pos_of[d] + 1 for d in since]
    out["move since bought"] = [
        pos.at[k, "price"] / px_wide.at[d, k] - 1 for k, d in since.items()
    ]  # close on the day bought -> close at t
    out["name"], out["rank"], out["momentum"] = None, pd.NA, float("nan")
    if picks is not None and len(picks):
        names = picks.dropna(subset=["name"]).drop_duplicates("ticker", keep="last")
        out["name"] = names.set_index("ticker")["name"].reindex(out.index)
        f = formation_for(picks, t)
        if f is not None:
            ranked = picks[picks["formation"] == f].set_index("ticker")
            out["rank"] = ranked["rank"].reindex(out.index)
            out["momentum"] = ranked["momentum"].reindex(out.index)
    cols = ["name", "weight", "value", "shares", "price", "held since", "trading days held",
            "move since bought", "rank", "momentum"]  # fmt: skip
    return out[cols].sort_values("weight", ascending=False)
