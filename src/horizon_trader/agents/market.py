"""Market inputs for the forecast journal: daily closes, option chains and the market packet.

The journal reads Yahoo directly instead of `datasources.store`: it runs during market hours
(option quotes are zero outside them), and caching a half-finished day in data/bars would feed
an intraday price to the evening shadow run as that day's close.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import numpy as np
import pandas as pd

# Market packet: broad market, sectors, rates, credit, dollar, commodities, crypto.
WATCH = {
    "SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000", "DIA": "Dow 30",
    "SMH": "semiconductors", "XLK": "tech", "XLF": "financials", "XLE": "energy",
    "XLV": "health care", "XLY": "consumer discretionary", "XLP": "consumer staples",
    "XLU": "utilities", "XLI": "industrials", "TLT": "20y+ Treasuries", "IEF": "7-10y Treasuries",
    "HYG": "high-yield credit", "LQD": "investment-grade credit", "UUP": "US dollar",
    "GLD": "gold", "USO": "oil", "IBIT": "bitcoin",
}  # fmt: skip
VOL = ["^VIX", "^VIX3M"]
IMPLIED = ["SPY", "QQQ", "IWM", "SMH"]  # options-implied ~1-week moves


class Market(Protocol):
    def closes(self, symbols: list[str], start: str) -> pd.DataFrame:
        """Date x ticker adjusted closes (today's row is the live price during market hours)."""

    def expiries(self, symbol: str) -> list[str]: ...

    def chain(self, symbol: str, expiry: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        """(calls, puts) with contractSymbol, strike, bid, ask, lastPrice, impliedVolatility."""

    def spot(self, symbol: str) -> float: ...

    def raw_close(self, symbol: str, day: str) -> float | None:
        """Unadjusted close on `day` (option settlement), None if not available."""


class YahooMarket:
    """yfinance for closes, expiries and chain structure (strikes, contract symbols, IV).

    Yahoo's option bid/ask are ~15 minutes delayed. With `quotes` (e.g.
    `datasources.ibkr_quotes.IBKRQuotes`), `requote` swaps in live bid/ask for the contracts
    that matter and falls back to Yahoo's per contract when the live source has nothing."""

    def __init__(self, quotes=None) -> None:
        import yfinance as yf

        from horizon_trader.config import data_dir

        yf.set_tz_cache_location(str(data_dir() / "yfinance-cache"))
        self.yf = yf
        self.quotes = quotes
        self._chains: dict[tuple[str, str], tuple[pd.DataFrame, pd.DataFrame]] = {}

    def closes(self, symbols: list[str], start: str) -> pd.DataFrame:
        raw = self.yf.download(
            symbols, start=start, auto_adjust=True, progress=False, threads=False
        )["Close"]
        if isinstance(raw, pd.Series):
            raw = raw.to_frame(symbols[0])
        raw.index = pd.DatetimeIndex(raw.index).tz_localize(None).normalize()
        return raw.dropna(how="all")

    def expiries(self, symbol: str) -> list[str]:
        return list(self.yf.Ticker(symbol).options)

    def chain(self, symbol: str, expiry: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        key = (symbol, expiry)
        if key not in self._chains:
            c = self.yf.Ticker(symbol).option_chain(expiry)
            self._chains[key] = (c.calls, c.puts)
        return self._chains[key]

    def spot(self, symbol: str) -> float:
        return float(self.yf.Ticker(symbol).fast_info["last_price"])

    def live_quotes(self, symbols: list[str]) -> dict[str, tuple[float, float]]:
        return self.quotes.quotes(symbols) if self.quotes is not None else {}

    def raw_close(self, symbol: str, day: str) -> float | None:
        d = pd.Timestamp(day)
        h = self.yf.Ticker(symbol).history(
            start=d.strftime("%Y-%m-%d"), end=(d + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            auto_adjust=False,
        )  # fmt: skip
        return float(h["Close"].iloc[-1]) if len(h) else None


# ---------- option helpers ----------


def live(row: pd.Series) -> bool:
    """A usable two-sided quote (Yahoo shows 0/0 outside market hours)."""
    return bool(row["bid"] > 0 and row["ask"] > 0 and row["ask"] >= row["bid"])


def requote(market: Market, rows: pd.DataFrame) -> pd.DataFrame:
    """`rows` (chain rows) with live bid/ask where the market has a live source for them.

    Adds `quote_source`: "ibkr" for a live quote, "yahoo" for the chain's own (delayed) one.
    Markets without `live_quotes` (tests, plain Yahoo) return the rows unchanged."""
    out = rows.reset_index(drop=True)  # rows from calls and puts can share index labels
    out["quote_source"] = "yahoo"
    fetch = getattr(market, "live_quotes", None)
    if fetch is None or out.empty:
        return out
    try:
        got = fetch([str(s) for s in out["contractSymbol"]])
    except Exception:  # noqa: BLE001 - the delayed quote is the fallback
        got = {}
    for i, sym in zip(out.index, out["contractSymbol"], strict=True):
        if sym in got:
            out.loc[i, ["bid", "ask"]] = got[sym]
            out.loc[i, "quote_source"] = "ibkr"
    return out


def nearest_expiry(expiries: list[str], today: str, days: int) -> str | None:
    t = pd.Timestamp(today)
    future = [e for e in expiries if pd.Timestamp(e) > t]
    if not future:
        return None
    return min(future, key=lambda e: abs((pd.Timestamp(e) - t).days - days))


@dataclass
class ImpliedMove:
    symbol: str
    expiry: str
    days: int
    move_pct: float | None
    source: str  # "mid, ibkr" / "mid, yahoo" (quotes), "last" (last trades) or "none"


def implied_move(market: Market, symbol: str, today: str, days: int = 7) -> ImpliedMove | None:
    """ATM straddle / spot: the move the options market prices to expiry."""
    expiry = nearest_expiry(market.expiries(symbol), today, days)
    if expiry is None:
        return None
    spot = market.spot(symbol)
    calls, puts = market.chain(symbol, expiry)
    k = calls["strike"].iloc[(calls["strike"] - spot).abs().argmin()]
    c, p = calls[calls["strike"] == k].iloc[0], puts[puts["strike"] == k]
    out_days = (pd.Timestamp(expiry) - pd.Timestamp(today)).days
    if p.empty:
        return ImpliedMove(symbol, expiry, out_days, None, "none")
    fresh = requote(market, pd.DataFrame([c, p.iloc[0]]))
    c, p = fresh.iloc[0], fresh.iloc[1]
    if live(c) and live(p):
        src = "ibkr" if c["quote_source"] == p["quote_source"] == "ibkr" else "yahoo"
        straddle, source = (c["bid"] + c["ask"] + p["bid"] + p["ask"]) / 2, f"mid, {src}"
    elif c["lastPrice"] > 0 and p["lastPrice"] > 0:
        straddle, source = c["lastPrice"] + p["lastPrice"], "last"
    else:
        return ImpliedMove(symbol, expiry, out_days, None, "none")
    return ImpliedMove(symbol, expiry, out_days, float(straddle / spot * 100), source)


# ---------- the packet ----------


def stats(closes: pd.DataFrame) -> pd.DataFrame:
    """Per ticker: last, 1/5/20-day return, vs 50/200-day average, 20d vol, off 52w high."""
    rows = {}
    for t in closes.columns:
        s = closes[t].dropna()
        if len(s) < 2:
            continue
        r = s.pct_change()
        rows[t] = {
            "last": s.iloc[-1],
            "1d %": (s.iloc[-1] / s.iloc[-2] - 1) * 100,
            "5d %": (s.iloc[-1] / s.iloc[-6] - 1) * 100 if len(s) > 5 else np.nan,
            "20d %": (s.iloc[-1] / s.iloc[-21] - 1) * 100 if len(s) > 20 else np.nan,
            "vs 50d %": (s.iloc[-1] / s.tail(50).mean() - 1) * 100 if len(s) >= 50 else np.nan,
            "vs 200d %": (s.iloc[-1] / s.tail(200).mean() - 1) * 100 if len(s) >= 200 else np.nan,
            "vol 20d %": r.tail(20).std() * np.sqrt(252) * 100 if len(s) > 20 else np.nan,
            "off 52w high %": (s.iloc[-1] / s.tail(252).max() - 1) * 100,
        }
    return pd.DataFrame(rows).T


def packet(market: Market, today: str) -> tuple[str, dict]:
    """The market packet every agent sees: (markdown, json-able numbers)."""
    start = (pd.Timestamp(today) - pd.Timedelta(days=420)).strftime("%Y-%m-%d")
    closes = market.closes([*WATCH, *VOL], start)
    closes = closes.loc[: pd.Timestamp(today)]
    st = stats(closes[[c for c in WATCH if c in closes]])
    st.insert(0, "what", [WATCH[t] for t in st.index])
    vix = closes.get("^VIX", pd.Series(dtype=float)).dropna()
    vix3m = closes.get("^VIX3M", pd.Series(dtype=float)).dropna()
    credit = (closes["HYG"] / closes["IEF"]).dropna() if {"HYG", "IEF"} <= set(closes) else None
    moves = [m for s in IMPLIED if (m := _safe_move(market, s, today))]

    nums: dict = {"asof": today, "last_bar": closes.index[-1].strftime("%Y-%m-%d")}
    nums["tickers"] = st.drop(columns="what").round(3).to_dict(orient="index")
    lines = [
        f"# Market packet, {today}",
        "",
        f"Daily closes to {nums['last_bar']} (the last row is the live price during market"
        " hours). Returns in %, adjusted for dividends.",
        "",
        "| ticker | what | " + " | ".join(st.columns[1:]) + " |",
        "|---" * (len(st.columns) + 1) + "|",
    ]
    for t, row in st.iterrows():
        cells = ["" if pd.isna(v) else f"{v:,.1f}" for v in row.iloc[1:]]
        lines.append(f"| {t} | {row['what']} | " + " | ".join(cells) + " |")
    if len(vix) and len(vix3m):
        ratio = vix.iloc[-1] / vix3m.iloc[-1]
        change = vix.iloc[-1] - vix.iloc[-6] if len(vix) > 5 else None
        nums["vix"] = {"vix": vix.iloc[-1], "vix3m": vix3m.iloc[-1], "ratio": ratio,
                       "vix_5d_change": change}  # fmt: skip
        lines += [
            "",
            "## Volatility",
            f"VIX {vix.iloc[-1]:.1f}, VIX3M {vix3m.iloc[-1]:.1f}, ratio {ratio:.2f} "
            "(above 1 = near-term fear exceeds 3-month: inverted term structure). "
            + (f"VIX 5 days ago: {vix.iloc[-6]:.1f}." if len(vix) > 5 else ""),
        ]
    if credit is not None and len(credit) > 21:
        c5, c20 = (
            (credit.iloc[-1] / credit.iloc[-6] - 1) * 100,
            (credit.iloc[-1] / credit.iloc[-21] - 1) * 100,
        )
        nums["credit"] = {"hyg_ief_5d_pct": c5, "hyg_ief_20d_pct": c20}
        lines += [
            "",
            "## Credit",
            f"High yield vs Treasuries (HYG/IEF): {c5:+.2f}% over 5 days, {c20:+.2f}% over 20 "
            "(falling = credit spreads widening).",
        ]
    if moves:
        nums["implied"] = [m.__dict__ for m in moves]
        lines += ["", "## Options-implied moves (ATM straddle / spot)"]
        for m in moves:
            mv = f"±{m.move_pct:.1f}%" if m.move_pct is not None else "no quote"
            lines.append(f"- {m.symbol} to {m.expiry} ({m.days} days): {mv} [{m.source}]")
    return "\n".join(lines) + "\n", nums


def _safe_move(market: Market, symbol: str, today: str) -> ImpliedMove | None:
    try:
        return implied_move(market, symbol, today)
    except Exception:  # noqa: BLE001 - one missing chain shouldn't stop the packet
        return None


def is_weekday(day: str) -> bool:
    return date.fromisoformat(day).weekday() < 5
