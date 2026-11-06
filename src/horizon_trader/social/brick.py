"""Following bricktrades' Discord option alerts: held to expiry, and stock direction.

    uv run python -m horizon_trader.social.brick [--export <file>]

Pre-registered in research/brick_alerts/protocol.md (2026-11-05, before any return was
computed). Input: a DiscordChatExporter JSON of the brick-alerts channel
(data/discord/raw/, see social/discord.py). No option prices are used:

  Test 1  each opening contract held to expiry: value = intrinsic value at the expiry
          day's official close (split-adjusted to the alert's share basis), return =
          value / his price - 1. The option's market price is the control.
  Test 2  the stock bought 1 minute after the alert (calls long, puts short), 5 / 20
          trading days and to expiry, vs QQQ bought at the same moment, raw and
          beta-adjusted (120-day beta before the alert).

His own follow-ups ("UPST 105% first trim") are reported as claims, never as returns.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.datasources import massive
from horizon_trader.social import discord
from horizon_trader.social import event_study as E

CHANNEL = "1315498906036994129"  # Low Key Stonks / brick-alerts
AUTHOR = "bricktrades"
PRICE_START = date(2024, 5, 1)  # 120+ trading days before the first alert, for beta
HALF_SPLIT = pd.Timestamp("2025-12-01", tz=E.TZ)  # first half = alerts before this
HORIZONS = (5, 20)
BETA_DAYS, BETA_MIN = 120, 60
FOLLOWER_MARKUP = 0.05  # sensitivity: a follower pays 5% more than his price
DTE_BUCKETS = [(7, "<= 7 days"), (30, "8-30 days"), (90, "31-90 days"), (10**6, "> 90 days")]

# ---------------------------------------------------------------- parsing

# capitalised words that sit where a ticker would and aren't one in his alerts
STOPWORDS = set(
    "I ER AH PM AM SL PT TP ATH ATL IPO DTE ITM OTM ATM LOD HOD NLOD IV MA EMA SMA RSI "
    "DD EOD EOW CPI FOMC NFP PPI GDP OI YOLO BTFD FYI IMO TMRW LOL OMG WTF NEW HIGH RISK "
    "PLAY CALL CALLS PUT PUTS C P".split()
)
TICKER = re.compile(r"^\$?([A-Z]{1,5})$")
STRIKE_CP = re.compile(r"^(\d+(?:\.\d+)?)([cp])$", re.I)
NUMBER = re.compile(r"^\$?(\d*\.\d+|\d+(?:\.\d+)?)$")
DATE_MD = re.compile(r"^(\d{1,2})/(\d{1,2})$")
DATE_MDY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")
DATE_MY = re.compile(r"^(\d{1,2})/(\d{4})$")
NDTE = re.compile(r"^(\d)dte$", re.I)
CP_WORDS = {"c": "c", "call": "c", "calls": "c", "p": "p", "put": "p", "puts": "p"}
EXCLUDE_LINE = re.compile(
    r"spread|covered|sold to open|\bsto\b|credit|iron condor|\d+/\d+\s*(?:long|debit)", re.I
)
FLOW = re.compile(r"prem:", re.I)
FOLLOWED_AT = re.compile(
    r"(?:follow\w*|took|taking|bought|in)\s*@\s*\$?(\d*\.\d+|\d+(?:\.\d+)?)", re.I
)
ADD_WORDS = re.compile(
    r"\b(add(?:ed|ing)?|double[d]? down|doubled|avg(?:d|ed)? (?:down|up)|re ?entered)\b", re.I
)
SHARES = re.compile(r"\d+\s*x\b|\bshares?\b", re.I)
CLAIM = re.compile(r"(?<![\w.])([+-]?\d+(?:\.\d+)?)\s?%(?!\s*(?:SL|stop))", re.I)
MENTION_TAGS = re.compile(r"@Brick Alerts|@HIGH RISK PLAY\S*", re.I)


@dataclass(frozen=True)
class Contract:
    ticker: str
    strike: float
    cp: str  # "c" or "p"
    expiry: date


class Calendar:
    """Trading days from the local Massive day files; weekdays after the last file."""

    def __init__(self, days: list[date]):
        self.days = sorted(days)
        self.last = self.days[-1] if self.days else date.min
        self._set = set(self.days)

    def is_trading(self, d: date) -> bool:
        return d in self._set if d <= self.last else d.weekday() < 5

    def on_or_before(self, d: date) -> date:
        while not self.is_trading(d):
            d -= timedelta(days=1)
        return d

    def add_trading_days(self, d: date, n: int) -> date:
        d = self.on_or_before(d) if not self.is_trading(d) else d
        while n > 0:
            d += timedelta(days=1)
            if self.is_trading(d):
                n -= 1
        return d


def third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def friday_of_week(d: date, weeks_ahead: int) -> date:
    """Friday of d's week (weeks start Monday) plus `weeks_ahead` weeks; a weekend post
    belongs to the coming week."""
    if d.weekday() >= 5:
        d += timedelta(days=7 - d.weekday())
        weeks_ahead -= 1 if weeks_ahead > 0 else 0
    return d + timedelta(days=4 - d.weekday() + 7 * weeks_ahead)


def _tokens(line: str) -> list[str]:
    line = line.replace("**", " ").replace("@", " @ ").replace(",", " ")
    out = []
    for t in line.split():
        t = t.strip("()[]!?;:\"'*~_")
        t = t.rstrip(".") if not re.fullmatch(r"\.\d+", t) else t
        if t:
            out.append(t)
    return out


def _expiry(tokens: list[str], i: int, posted: date, cal: Calendar) -> tuple[date, int] | None:
    """Expiry starting at token i: (date, tokens used) or None."""
    t = tokens[i]
    if m := DATE_MDY.match(t):
        mo, dy, yr = int(m[1]), int(m[2]), int(m[3])
        yr += 2000 if yr < 100 else 0
        return _safe_date(yr, mo, dy, cal), 1
    if m := DATE_MY.match(t):
        return cal.on_or_before(third_friday(int(m[2]), int(m[1]))), 1
    if m := DATE_MD.match(t):
        mo, dy = int(m[1]), int(m[2])
        d = _safe_date(posted.year, mo, dy, cal)
        if d is not None and d < posted:
            d = _safe_date(posted.year + 1, mo, dy, cal)
        return d, 1
    if m := NDTE.match(t):
        return cal.add_trading_days(posted, int(m[1])), 1
    nxt = tokens[i + 1].lower() if i + 1 < len(tokens) else ""
    if t.lower() in ("next", "nexxt", "nxt") and nxt.startswith("week"):
        return cal.on_or_before(friday_of_week(posted, 1)), 2
    if t.lower() == "this" and nxt.startswith("week"):
        return cal.on_or_before(friday_of_week(posted, 0)), 2
    if re.fullmatch(r"\d", t) and nxt == "dte":
        return cal.add_trading_days(posted, int(t)), 2
    return None


def _safe_date(y: int, m: int, d: int, cal: Calendar) -> date | None:
    try:
        return cal.on_or_before(date(y, m, d))
    except ValueError:
        return None


def _strike(tokens: list[str], i: int) -> tuple[float, str, int] | None:
    t = tokens[i]
    if m := STRIKE_CP.match(t):
        return float(m[1]), m[2].lower(), 1
    if NUMBER.match(t) and "$" not in t and i + 1 < len(tokens):
        cp = CP_WORDS.get(tokens[i + 1].lower())
        if cp:
            return float(NUMBER.match(t)[1]), cp, 2
    return None


def _price_at(tokens: list[str], i: int) -> float | None:
    t = tokens[i]
    if t.endswith("%") or "/" in t:
        return None
    m = NUMBER.match(t)
    if not m:
        return None
    nxt = tokens[i + 1].lower() if i + 1 < len(tokens) else ""
    if nxt in ("x", "shares", "share", "%", "dte") or nxt in CP_WORDS:
        return None
    return float(m[1])


def parse_line(line: str, posted: date, cal: Calendar) -> list[dict]:
    """Contract specs in one line: [{ticker, strike, cp, expiry, price}], with ticker,
    price or expiry None when the line doesn't give them (adds resolve those later)."""
    if EXCLUDE_LINE.search(line):
        return []
    tokens = _tokens(line)
    specs, i, last_ticker = [], 0, None
    while i < len(tokens):
        tm = TICKER.match(tokens[i])
        if tm and tm[1] not in STOPWORDS:
            last_ticker = tm[1]
            i += 1
            continue
        exp_first = _expiry(tokens, i, posted, cal)
        j = i + (exp_first[1] if exp_first else 0)
        st = _strike(tokens, j) if j < len(tokens) else None
        if st is None and exp_first is None:
            st = _strike(tokens, i)
            j = i
        if st is None:
            i += 1
            continue
        strike, cp, used = st
        k = j + used
        expiry = exp_first[0] if exp_first else None
        price = None
        # scan the rest of the line (up to the next contract) for the expiry and the price;
        # a price after '@' / 'for' wins
        while k < len(tokens):
            if _strike(tokens, k) and expiry is not None:
                break
            if expiry is None and (e := _expiry(tokens, k, posted, cal)):
                expiry = e[0]
                k += e[1]
                continue
            tok = tokens[k]
            if tok in ("@",) or tok.lower() == "for":
                if k + 1 < len(tokens) and (p := _price_at(tokens, k + 1)) is not None:
                    price = p
                    k += 2
                    break
            if price is None and (p := _price_at(tokens, k)) is not None:
                price = p
                if expiry is not None:
                    k += 1
                    break
            if TICKER.match(tok) and TICKER.match(tok)[1] not in STOPWORDS and price is not None:
                break
            k += 1
        specs.append(
            {"ticker": last_ticker, "strike": strike, "cp": cp, "expiry": expiry, "price": price}
        )
        i = max(k, i + 1)
    return specs


def _first_ticker(tokens: list[str]) -> str | None:
    return next((m[1] for t in tokens if (m := TICKER.match(t)) and m[1] not in STOPWORDS), None)


def parse_message(text: str, posted: date, cal: Calendar) -> dict:
    """{lines, flow, followed_price, high_risk, watchlist}: per line, the contract specs
    (parse_line) or else a plain add (plain_add), plus the message-level context."""
    clean = MENTION_TAGS.sub(" ", text)
    fm = FOLLOWED_AT.search(clean)
    fallback = _first_ticker(_tokens(clean))
    lines = []
    for line in clean.splitlines():
        specs = [
            s if s["ticker"] else {**s, "ticker": fallback} for s in parse_line(line, posted, cal)
        ]
        lines.append((specs, None if specs else plain_add(line, fallback)))
    return {
        "lines": lines,
        "flow": bool(FLOW.search(clean)),
        "followed_price": float(fm[1]) if fm else None,
        "high_risk": "HIGH RISK" in text.upper(),
        "watchlist": "watchlist" in clean.lower(),
    }


def plain_add(line: str, fallback: str | None = None) -> tuple[str, float | None, float] | None:
    """An add without a full contract: 'MRVL add @ 2.4', 'UBER added 2.25', 'Avgd up @ 3.00'
    (ticker from earlier in the message). (ticker, strike or None, price); share buys and
    lines without an add word give None."""
    if not ADD_WORDS.search(line) or SHARES.search(line) or EXCLUDE_LINE.search(line):
        return None
    tokens = _tokens(line)
    ticker = _first_ticker(tokens) or fallback
    if ticker is None:
        return None
    strike = next((st[0] for i in range(len(tokens)) if (st := _strike(tokens, i))), None)
    price = None
    for i, t in enumerate(tokens):
        if (t == "@" or t.lower() == "for") and i + 1 < len(tokens):
            if (price := _price_at(tokens, i + 1)) is not None:
                break
    if price is None:  # 'UBER added 2.25'
        for i, t in enumerate(tokens):
            if ADD_WORDS.fullmatch(t.lower()) and i + 1 < len(tokens):
                price = _price_at(tokens, i + 1)
                break
    return (ticker, strike, price) if price is not None else None


def extract_alerts(msgs: pd.DataFrame, cal: Calendar, author: str = AUTHOR) -> pd.DataFrame:
    """Every purchase he alerts: one row per contract leg, kind = 'open' (first alert of
    that contract) or 'add'. Columns: msg_id, leg, ts, ticker, strike, cp, expiry, price,
    kind, high_risk, edited, is_reply, contract (key)."""
    rows, opened = [], {}  # contract -> first row; ticker -> latest open contracts
    latest: dict[str, list[Contract]] = {}
    mine = msgs[(msgs["author"] == author) & ~msgs["is_bot"]]
    for m in mine.itertuples():
        posted = m.ts.date()
        p = parse_message(m.content, posted, cal)
        if p["watchlist"]:
            continue
        legs = []
        for specs, add in p["lines"]:
            for s in specs:
                # a flow repost ('TICK 18 C 03/21/2025 / Prem: $258,808') has no price: it
                # counts only if he says he followed it at a price
                price = s["price"]
                if price is None and p["flow"]:
                    price = p["followed_price"]
                if s["ticker"] is None or price is None or price <= 0:
                    continue
                if s["expiry"] is None:  # a strike without expiry: add to an open contract
                    match = [
                        c
                        for c in latest.get(s["ticker"], [])
                        if c.strike == s["strike"] and c.expiry >= posted
                    ]
                    if not match:
                        continue
                    c = match[-1]
                else:
                    if s["expiry"] < posted:
                        continue
                    c = Contract(s["ticker"], s["strike"], s["cp"], s["expiry"])
                legs.append((c, price))
            if add is not None:
                ticker, strike, price = add
                cands = [
                    c
                    for c in latest.get(ticker, [])
                    if c.expiry >= posted and (strike is None or c.strike == strike)
                ]
                if cands:
                    legs.append((cands[-1], price))
        for leg, (c, price) in enumerate(legs):
            kind = "add" if c in opened else "open"
            if kind == "open":
                opened[c] = m.id
                latest.setdefault(c.ticker, []).append(c)
            rows.append(
                {
                    "msg_id": m.id,
                    "leg": leg,
                    "ts": m.ts,
                    "ticker": c.ticker,
                    "strike": c.strike,
                    "cp": c.cp,
                    "expiry": c.expiry,
                    "price": price,
                    "kind": kind,
                    "high_risk": p["high_risk"],
                    "edited": m.edited_ts is not None and not pd.isna(m.edited_ts),
                    "is_reply": isinstance(m.reply_to, str),
                    "contract": f"{c.ticker} {c.strike:g}{c.cp} {c.expiry:%Y-%m-%d}",
                }
            )
    return pd.DataFrame(rows)


def unparsed(msgs: pd.DataFrame, alerts: pd.DataFrame, author: str = AUTHOR) -> pd.DataFrame:
    """His messages that mention a strike (e.g. '60c') but produced no alert: the parser's
    misses, for the coverage report."""
    loose = re.compile(r"\d+(?:\.\d+)?\s?(?:c|p|calls?|puts?)\b", re.I)
    mine = msgs[(msgs["author"] == author) & msgs["content"].str.contains(loose)]
    return mine[~mine["id"].isin(set(alerts["msg_id"]))]


# ---------------------------------------------------------------- his follow-up claims


def claims(msgs: pd.DataFrame, alerts: pd.DataFrame, author: str = AUTHOR) -> pd.DataFrame:
    """Replies by him that trace back (through reply chains) to an opening alert and carry
    a % figure: [contract, ts, claim]. Self-reported; descriptive only."""
    opens = alerts[alerts["kind"] == "open"]
    by_msg = {k: g for k, g in opens.groupby("msg_id")}
    parent = dict(zip(msgs["id"], msgs["reply_to"], strict=True))
    rows = []
    mine = msgs[(msgs["author"] == author) & msgs["reply_to"].notna()]
    for m in mine.itertuples():
        found = CLAIM.findall(MENTION_TAGS.sub(" ", m.content))
        if not found:
            continue
        target, hops = m.reply_to, 0
        while target is not None and target not in by_msg and hops < 10:
            target, hops = parent.get(target), hops + 1
        if target not in by_msg:
            continue
        legs = by_msg[target]
        text = m.content
        named = legs[[re.search(rf"\b{t}\b", text) is not None for t in legs["ticker"]]]
        legs = named if len(named) else legs
        if len(legs) != 1:
            continue  # a multi-leg alert and the reply doesn't say which leg
        rows.append(
            {"contract": legs["contract"].iloc[0], "ts": m.ts, "claim": float(found[0]) / 100}
        )
    return pd.DataFrame(rows, columns=["contract", "ts", "claim"])


# ---------------------------------------------------------------- pricing


def payoff(cp: str, strike: float, spot: float) -> float:
    return max(spot - strike, 0.0) if cp == "c" else max(strike - spot, 0.0)


def attach_stock(alerts: pd.DataFrame, px: dict) -> pd.DataFrame:
    """Stock prices at each alert via the Serenity study's timing (his price = the last
    completed minute; follower = 1 minute later, else the next open), QQQ at the same
    moment, the official close on the expiry day in the alert's share basis, and beta."""
    ments = alerts.assign(
        id=alerts["msg_id"] + ":" + alerts["leg"].astype(str), first_mention=False
    )
    calls = E.build_calls(ments[["id", "ts", "ticker", "first_mention"]], px)
    ev = E._attach_prices(calls, px)
    ev = E.forward_returns(ev, px, horizons=HORIZONS)
    keep = ["id", "row", "entry", "entry_mode", "entry_date", "ref", "px_1m", "QQQ_px_1m"]
    keep += ["dollar_vol"]
    keep += [c for c in ev if c.startswith(("ret_", "QQQ_ret_", "SPY_ret_"))]
    out = ments.merge(ev[keep], on="id", how="left")

    days = px["close"].index
    pos = {d.date(): i for i, d in enumerate(days)}
    exp_row = out["expiry"].map(lambda d: pos.get(d, -1)).astype(int)
    tick = out["ticker"]
    alert_row = out["row"].fillna(-1).astype(int)
    close_exp = E._lookup(px["close"], exp_row.where(exp_row >= 0, -1), tick)
    f_exp = E._lookup(px["factor"], exp_row.where(exp_row >= 0, -1), tick)
    f_alert = E._lookup(px["factor"], alert_row, tick)
    out["expired"] = exp_row >= 0
    out["spot_expiry"] = close_exp * f_exp / f_alert  # in the alert's share basis
    out["value_expiry"] = [
        payoff(c, k, s) if np.isfinite(s) else np.nan
        for c, k, s in zip(out["cp"], out["strike"], out["spot_expiry"], strict=True)
    ]
    out["R"] = out["value_expiry"] / out["price"] - 1
    out["R_follower"] = out["value_expiry"] / (out["price"] * (1 + FOLLOWER_MARKUP)) - 1

    # stock to expiry, from the follower's price; QQQ over the same span
    adj = px["adj"].ffill()
    entry = out["entry"].fillna(-1).astype(int)
    f_entry = E._lookup(px["factor"], entry, tick)
    q = pd.Series("QQQ", index=out.index)
    out["ret_exp"] = E._lookup(adj, exp_row, tick) / (out["px_1m"] * f_entry) - 1
    q_entry = out["QQQ_px_1m"] * E._lookup(px["factor"], entry, q)
    out["QQQ_ret_exp"] = E._lookup(adj, exp_row, q) / q_entry - 1
    out.loc[exp_row < 0, ["ret_exp", "QQQ_ret_exp"]] = np.nan

    out["beta"] = betas(px["adj"], alert_row, tick)
    out["dte"] = [(e - t.date()).days for e, t in zip(out["expiry"], out["ts"], strict=True)]
    out["moneyness"] = np.where(
        out["cp"] == "c", out["strike"] / out["ref"] - 1, 1 - out["strike"] / out["ref"]
    )
    return out


def betas(adj: pd.DataFrame, rows: pd.Series, tickers: pd.Series) -> np.ndarray:
    """Beta to QQQ from the BETA_DAYS daily returns ending the day before each alert's
    signal row (at least BETA_MIN, else 1)."""
    rets = adj.pct_change()
    q = rets["QQQ"].to_numpy()
    out = np.ones(len(rows))
    for i, (r, t) in enumerate(zip(rows, tickers, strict=True)):
        if r <= 0 or t not in rets:
            continue
        lo = max(r - BETA_DAYS, 1)
        y, x = rets[t].to_numpy()[lo:r], q[lo:r]
        ok = np.isfinite(y) & np.isfinite(x)
        if ok.sum() >= BETA_MIN and x[ok].var() > 0:
            out[i] = np.cov(y[ok], x[ok])[0, 1] / x[ok].var(ddof=1)
    return out


def add_excess(ev: pd.DataFrame) -> pd.DataFrame:
    ev = ev.copy()
    sign = np.where(ev["cp"] == "c", 1.0, -1.0)
    for h in (*(f"{h}d" for h in HORIZONS), "exp"):
        r, qr = ev[f"ret_{h}"], ev[f"QQQ_ret_{h}"]
        ev[f"sxs_QQQ_{h}"] = sign * (r - qr)
        ev[f"sxs_beta_{h}"] = sign * (r - ev["beta"] * qr)
        ev[f"signed_{h}"] = sign * r
    return ev


def timing_control(ev: pd.DataFrame, px: dict, h: int = 20) -> pd.Series:
    """Signed 20-day return minus the same stock's mean 20-day return over every start day
    between the first and the last alert."""
    adj = px["adj"].ffill()
    fwd = adj.shift(-h) / adj - 1
    span = (fwd.index >= ev["entry_date"].min()) & (fwd.index <= ev["entry_date"].max())
    base = fwd[span].mean()
    sign = np.where(ev["cp"] == "c", 1.0, -1.0)
    return pd.Series(sign * (ev[f"ret_{h}d"] - ev["ticker"].map(base)), index=ev.index)


# ---------------------------------------------------------------- reports


def dte_bucket(dte: pd.Series) -> pd.Series:
    out = pd.Series("", index=dte.index)
    for cap, label in reversed(DTE_BUCKETS):
        out[dte <= cap] = label
    return out


def option_table(ev: pd.DataFrame) -> pd.DataFrame:
    week = ev["ts"].dt.tz_localize(None).dt.to_period("W")
    first = ev["ts"] < HALF_SPLIT
    groups = {
        "all openings": ev.index,
        "calls": ev.index[ev["cp"] == "c"],
        "puts": ev.index[ev["cp"] == "p"],
        **{lab: ev.index[dte_bucket(ev["dte"]) == lab] for _, lab in DTE_BUCKETS},
        "HIGH RISK tag": ev.index[ev["high_risk"]],
        "no tag": ev.index[~ev["high_risk"]],
        "edited": ev.index[ev["edited"]],
        "not edited": ev.index[~ev["edited"]],
        "first half (to Nov 2025)": ev.index[first],
        "second half (Dec 2025-)": ev.index[~first],
    }
    rows = []
    for name, idx in groups.items():
        r = ev.loc[idx, "R"].dropna()
        if r.empty:
            continue
        rows.append(
            {
                "group": name,
                "n": len(r),
                "mean R": r.mean(),
                "median R": r.median(),
                "% worthless": (r <= -0.999).mean(),
                "% profit": (r > 0).mean(),
                "t (weekly)": E.clustered_t(r, week.loc[r.index]),
                "mean R +5% fill": ev.loc[r.index, "R_follower"].mean(),
                "top 5% share of gains": top_share(r),
            }
        )
    return pd.DataFrame(rows).set_index("group")


def top_share(r: pd.Series) -> float:
    """Share of the total profit (sum of R over winners and losers) that the best 5% of
    alerts make up: > 100% means the rest lose money together."""
    total = r.sum()
    k = max(1, int(np.ceil(len(r) * 0.05)))
    return r.nlargest(k).sum() / total if total > 0 else np.nan


def stock_table(ev: pd.DataFrame) -> pd.DataFrame:
    week = ev["ts"].dt.tz_localize(None).dt.to_period("W")
    first = ev["ts"] < HALF_SPLIT
    rows = []
    for h in (*(f"{h}d" for h in HORIZONS), "exp"):
        for name, mask in {
            "all": pd.Series(True, index=ev.index),
            "first half": first,
            "second half": ~first,
            "calls": ev["cp"] == "c",
            "puts": ev["cp"] == "p",
        }.items():
            sub = ev[mask].dropna(subset=[f"sxs_beta_{h}"])
            if sub.empty:
                continue
            x = sub[f"sxs_beta_{h}"]
            rows.append(
                {
                    "horizon": "to expiry" if h == "exp" else h,
                    "group": name,
                    "n": len(sub),
                    "stock (signed)": sub[f"signed_{h}"].mean(),
                    "vs QQQ": sub[f"sxs_QQQ_{h}"].mean(),
                    "beta-adj vs QQQ": x.mean(),
                    "median beta-adj": x.median(),
                    "% beat (beta-adj)": (x > 0).mean(),
                    "t (weekly)": E.clustered_t(x, week.loc[x.index]),
                }
            )
    return pd.DataFrame(rows).set_index(["horizon", "group"])


def _fmt(df: pd.DataFrame, pct: list[str], num: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in pct:
        out[c] = df[c].map(lambda v: "-" if pd.isna(v) else f"{v:+.1%}")
    for c in num:
        out[c] = df[c].map(lambda v: "-" if pd.isna(v) else f"{v:.2f}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--export", type=Path, help="DiscordChatExporter JSON (default: latest)")
    p.add_argument("--show-unparsed", type=int, default=0, help="print N unparsed messages")
    sys.stdout.reconfigure(encoding="utf-8")  # emoji in messages on a Windows console
    args = p.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)

    msgs = discord.load(CHANNEL, args.export)
    cal = Calendar(massive.local_days("day"))
    alerts = extract_alerts(msgs, cal)
    miss = unparsed(msgs, alerts)
    opens = alerts[alerts["kind"] == "open"]
    print(
        f"messages {len(msgs):,} ({(msgs['author'] == AUTHOR).sum():,} by {AUTHOR}); "
        f"alerted purchases {len(alerts):,} = {len(opens):,} openings + "
        f"{(alerts['kind'] == 'add').sum():,} adds; {len(miss):,} of his messages mention a "
        f"strike but gave no alert (spreads, flow reposts, no price, no ticker...)"
    )
    for m in miss.sample(min(args.show_unparsed, len(miss)), random_state=0).itertuples():
        print(
            "   unparsed:",
            m.ts.strftime("%Y-%m-%d %H:%M"),
            "|",
            m.content[:140].replace("\n", " / "),
        )

    px = E.load_prices(set(alerts["ticker"]) | {"QQQ"}, start=PRICE_START)
    ev = attach_stock(alerts, px)
    ok = ev["ref"].notna() & (ev["price"] < ev["ref"])
    ok &= (ev["strike"] > 0.2 * ev["ref"]) & (ev["strike"] < 5 * ev["ref"])
    print(
        f"testable (US bars at the alert, sane price and strike): {ok.sum():,} of {len(ev):,}; "
        f"expired by {px['close'].index[-1].date()}: {(ok & ev['expired']).sum():,}"
    )
    lost = ev.loc[~ev["ticker"].isin(px["close"].columns), "ticker"].value_counts()
    if len(lost):
        print("  no Massive bars:", ", ".join(f"{t} ({n})" for t, n in lost.head(10).items()))
    ev = add_excess(ev[ok])
    ev["timing_20d"] = timing_control(ev, px)
    ev["dte"] = ev["dte"].astype(int)

    o = ev[(ev["kind"] == "open") & ev["expired"]]
    print("\n=== Test 1: opening contracts held to expiry (return on his price) ===")
    t1 = option_table(o)
    pct = [
        "mean R",
        "median R",
        "% worthless",
        "% profit",
        "mean R +5% fill",
        "top 5% share of gains",
    ]
    print(_fmt(t1, pct, ["t (weekly)"]).to_string())
    prem, value = o["price"].sum(), o["value_expiry"].sum()
    print(
        f"  1 contract per opening: premium ${100 * prem:,.0f}, value at expiry "
        f"${100 * value:,.0f} -> {value / prem - 1:+.1%}"
    )
    print(
        f"  median days to expiry {o['dte'].median():.0f}, "
        f"median moneyness (OTM +) {o['moneyness'].median():+.1%}"
    )

    allp = ev[ev["expired"]]
    print(
        f"\nevery purchase (openings + adds) held to expiry: n={len(allp):,}, mean R "
        f"{allp['R'].mean():+.1%}, median {allp['R'].median():+.1%}; adds alone: "
        f"{allp.loc[allp['kind'] == 'add', 'R'].mean():+.1%} (n={(allp['kind'] == 'add').sum()})"
    )

    print("\n=== Test 2: the stock, bought 1 minute after the alert (puts = short), signed ===")
    s = ev[ev["kind"] == "open"]
    t2 = stock_table(s)
    pct = ["stock (signed)", "vs QQQ", "beta-adj vs QQQ", "median beta-adj", "% beat (beta-adj)"]
    print(_fmt(t2, pct, ["t (weekly)"]).to_string())
    print(f"  median beta to QQQ {s['beta'].median():.2f}")
    tc = s["timing_20d"].dropna()
    week = s.loc[tc.index, "ts"].dt.tz_localize(None).dt.to_period("W")
    print(
        f"  timing (20d vs the same stock's average 20d over the sample): mean {tc.mean():+.1%}, "
        f"t {E.clustered_t(tc, week):.2f}, n={len(tc)}"
    )

    print("\n=== his own follow-up claims (self-reported, descriptive) ===")
    cl = claims(msgs, alerts)
    best = cl.groupby("contract")["claim"].max()
    oc = o.set_index("contract")
    have = best.reindex(oc.index)
    print(
        f"expired openings with a % follow-up: {have.notna().sum()} of {len(oc)}; "
        f"of those, claimed a gain: {(have > 0).sum()}; median best claim {have.median():+.0%}"
    )
    both = pd.DataFrame({"claim": have, "R": oc["R"]}).dropna()
    if len(both):
        won = both["claim"] > 0
        print(
            f"  claimed a gain but worthless at expiry: {(won & (both['R'] <= -0.999)).sum()}"
            f" of {won.sum()}"
        )
    no_follow = oc[have.isna()]
    print(
        f"  openings with no % follow-up: n={len(no_follow)}, mean R {no_follow['R'].mean():+.1%}, "
        f"% worthless {(no_follow['R'] <= -0.999).mean():.0%}"
    )

    print("\n=== 10 best and 10 worst openings held to expiry ===")
    show = ["ts", "contract", "price", "dte", "moneyness", "spot_expiry", "R"]
    fmt = o[show].assign(ts=o["ts"].dt.strftime("%Y-%m-%d %H:%M"))
    print(fmt.nlargest(10, "R").to_string(index=False))
    print(fmt.nsmallest(10, "R").to_string(index=False))

    out = discord.root() / "derived"
    out.mkdir(parents=True, exist_ok=True)
    ev.drop(columns=["row", "entry"]).to_parquet(out / "brick_events.parquet")
    print(f"\nevent table -> {out / 'brick_events.parquet'}")


if __name__ == "__main__":
    main()
