"""SEC EDGAR: point-in-time fundamentals (XBRL company facts) and 10-K text, free.

    uv run python -m horizon_trader.datasources.sec download [--no-text]  # resumable, ~15 min
    uv run python -m horizon_trader.datasources.sec check                 # Apple's latest 10-Ks

Needs SEC_USER_AGENT in .env (SEC refuses requests without a contact). Caches gzipped JSON
under <data_dir>/sec/. The companies are every CIK that was ever among the 200 largest US
companies in Massive's point-in-time market caps (data/massive/reference/market_caps.parquet).

Point-in-time rule: every fundamental comes from a company's ORIGINAL 10-K (amendments are
ignored) and is usable only from the day after its `filed` date. That's what an investor
could have known; restated numbers never leak backwards.
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

from horizon_trader.config import data_dir

MAX_PER_SECOND = 8  # SEC allows 10 requests/second per client
TEXT_SINCE = "2019-01-01"  # 10-Ks needed: the one before the first test year, for similarity

# First tag present wins. Companies switch tags over time (ASC 606 revenue in 2018).
FLOW_TAGS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "cogs": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
    ],
    "gross_profit": ["GrossProfit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
}
STOCK_TAGS = {
    "assets": ["Assets"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
}
FIELDS = [*FLOW_TAGS, *STOCK_TAGS]
ANNUAL_DAYS = (330, 400)  # a fiscal-year duration; 52/53-week years land in range


# ---------- HTTP ----------


class _RateLimiter:
    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = self.next - now
            self.next = max(now, self.next) + self.interval
        if delay > 0:
            time.sleep(delay)


_LIMIT = _RateLimiter(MAX_PER_SECOND)


def _get(url: str) -> bytes | None:
    """GET with SEC's required User-Agent; None on 404 (no XBRL facts for that company)."""
    import horizon_trader.config  # noqa: F401  (loads .env)

    agent = os.environ.get("SEC_USER_AGENT")
    if not agent:
        raise SystemExit('Set SEC_USER_AGENT in .env, e.g. "horizon-trader you@example.com".')
    req = urllib.request.Request(url, headers={"User-Agent": agent, "Accept-Encoding": "gzip"})
    for attempt in range(6):
        _LIMIT.wait()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code not in (403, 429) and e.code < 500:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(2**attempt)  # throttled or a hiccup: back off
    raise RuntimeError(f"giving up on {url}")


def sec_dir() -> Path:
    return data_dir() / "sec"


def _cik10(cik: str | int) -> str:
    return str(int(cik)).zfill(10)


def _fresh(path: Path, max_age_days: float | None) -> bool:
    """A cached file counts if it exists and, when max_age_days is given, is young enough."""
    if not path.exists():
        return False
    return max_age_days is None or (time.time() - path.stat().st_mtime) < max_age_days * 86400


def _cached_json(path: Path, url: str, max_age_days: float | None = None) -> dict | None:
    if _fresh(path, max_age_days):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    body = _get(url)
    data = json.loads(body) if body is not None else {}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    tmp.replace(path)
    return data or None


def company_facts(cik: str | int, max_age_days: float | None = None) -> dict | None:
    """XBRL facts, cached. Pass max_age_days to re-download a cache older than that (new
    quarters arrive every ~3 months; the monthly LLM scorer uses 1 day)."""
    c = _cik10(cik)
    return _cached_json(
        sec_dir() / "companyfacts" / f"CIK{c}.json.gz",
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c}.json",
        max_age_days,
    )


def submissions(cik: str | int, max_age_days: float | None = None) -> dict | None:
    """Filing index. Busy filers (banks issue thousands of notes) spill older filings into
    extra pages; those are merged in until the pages reach back past TEXT_SINCE."""
    c = _cik10(cik)
    path = sec_dir() / "submissions" / f"CIK{c}.json.gz"
    if _fresh(path, max_age_days):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    body = _get(f"https://data.sec.gov/submissions/CIK{c}.json")
    if body is None:
        return None
    data = json.loads(body)
    recent = data["filings"]["recent"]
    for extra in data["filings"].get("files", []):
        if extra.get("filingTo", "9999") < TEXT_SINCE:
            continue
        more = _get(f"https://data.sec.gov/submissions/{extra['name']}")
        if more:
            for k, v in json.loads(more).items():
                if k in recent:
                    recent[k] = recent[k] + v
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    return data


# ---------- fundamentals ----------


def tenk_table(facts: dict | None) -> pd.DataFrame:
    """One row per original 10-K: accn, filed, period_end and the FIELDS (NaN when a tag is
    missing, e.g. banks have no gross profit). period_end is the latest balance-sheet date
    in the filing; flows are the fiscal-year values ending there, not prior-year comparatives."""
    cols = ["accn", "filed", "period_end", *FIELDS]
    gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    rows: dict[str, dict[str, Any]] = {}

    def entries(tag: str) -> list[dict]:
        return [e for e in gaap.get(tag, {}).get("units", {}).get("USD", []) if e["form"] == "10-K"]

    for kind, tag_lists in (("stock", STOCK_TAGS.values()), ("flow", FLOW_TAGS.values())):
        for tag in (t for tags in tag_lists for t in tags):
            for e in entries(tag):
                r = rows.setdefault(e["accn"], {"accn": e["accn"], "filed": e["filed"]})
                if kind == "stock":
                    r["period_end"] = max(r.get("period_end", ""), e["end"])

    for r in rows.values():
        if "period_end" not in r:  # no balance sheet facts: fall back to annual flows
            ends = [
                e["end"]
                for tags in FLOW_TAGS.values()
                for t in tags
                for e in entries(t)
                if e["accn"] == r["accn"] and _is_annual(e)
            ]
            if ends:
                r["period_end"] = max(ends)

    for field, tags in (*FLOW_TAGS.items(), *STOCK_TAGS.items()):
        flow = field in FLOW_TAGS
        for r in rows.values():
            for tag in tags:
                vals = [
                    e["val"]
                    for e in entries(tag)
                    if e["accn"] == r["accn"]
                    and e["end"] == r.get("period_end")
                    and (not flow or _is_annual(e))
                ]
                if vals:
                    r[field] = float(vals[0])
                    break

    df = pd.DataFrame(list(rows.values())).reindex(columns=cols)
    df = df.dropna(subset=["period_end"])
    missing_gp = df["gross_profit"].isna()
    df.loc[missing_gp, "gross_profit"] = (df["revenue"] - df["cogs"])[missing_gp]
    df["filed"] = pd.to_datetime(df["filed"])
    df["period_end"] = pd.to_datetime(df["period_end"])
    # Some filers report a 10-K twice under one period (e.g. a transition filing); keep the first.
    return df.sort_values("filed").drop_duplicates("period_end").reset_index(drop=True)


def _is_annual(e: dict) -> bool:
    if "start" not in e:
        return False
    days = (pd.Timestamp(e["end"]) - pd.Timestamp(e["start"])).days
    return ANNUAL_DAYS[0] <= days <= ANNUAL_DAYS[1]


def fundamentals_panel(ciks: list[str]) -> pd.DataFrame:
    """All cached companies' 10-K rows with a `cik` column (downloads missing ones)."""
    frames = [tenk_table(company_facts(c)).assign(cik=_cik10(c)) for c in ciks]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------- 10-K text ----------

_HIDDEN = re.compile(r"<ix:header>.*?</ix:header>", re.S | re.I)
_BLOCKS = re.compile(r"<(script|style|head)[^>]*>.*?</\1>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
_WORDS = re.compile(r"[a-z]{2,}")


def clean_words(raw_html: str) -> list[str]:
    """Lower-case words of a filing's visible text: inline-XBRL headers, scripts and tags
    dropped, numbers ignored (Cohen, Malloy & Nguyen compare words)."""
    text = _BLOCKS.sub(" ", _HIDDEN.sub(" ", raw_html))
    text = html.unescape(_TAGS.sub(" ", text)).lower()
    return _WORDS.findall(text)


def filings(
    subs: dict | None, forms: tuple[str, ...] = ("10-K",), since: str = TEXT_SINCE
) -> pd.DataFrame:
    """Original filings of the given forms (amendments are separate forms, so excluded) filed
    since `since`: accn, form, filed, period, doc."""
    cols = ["accn", "form", "filed", "period", "doc"]
    if not subs:
        return pd.DataFrame(columns=cols)
    r = subs["filings"]["recent"]
    df = pd.DataFrame(
        {
            "accn": r["accessionNumber"],
            "form": r["form"],
            "filed": r["filingDate"],
            "period": r["reportDate"],
            "doc": r["primaryDocument"],
        }
    )
    df = df[df["form"].isin(forms) & (df["filed"] >= since) & (df["doc"] != "")]
    df = df.drop_duplicates("accn")
    df["filed"] = pd.to_datetime(df["filed"])
    return df[cols].sort_values("filed").reset_index(drop=True)


def tenk_filings(subs: dict | None, since: str = TEXT_SINCE) -> pd.DataFrame:
    """Original 10-Ks (no amendments) filed since `since`."""
    return filings(subs, ("10-K",), since)


def tenk_word_counts(cik: str | int, accn: str, doc: str) -> Counter:
    path = sec_dir() / "tenk" / _cik10(cik) / f"{accn}.json.gz"
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return Counter(json.load(f))
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/{doc}"
    body = _get(url)
    counts = Counter(clean_words(body.decode("utf-8", errors="ignore"))) if body else Counter()
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(counts, f)
    return counts


def cosine(a: Counter, b: Counter) -> float:
    """Cosine similarity of two word-count vectors (1 = the same words in the same mix)."""
    if not a or not b:
        return float("nan")
    dot = sum(v * b.get(w, 0) for w, v in a.items())
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    return dot / (na * nb)


def similarity_table(cik: str | int) -> pd.DataFrame:
    """Each 10-K's cosine similarity to the same company's previous 10-K ("Lazy Prices")."""
    filings = tenk_filings(submissions(cik))
    rows, prev = [], None
    for f in filings.itertuples():
        counts = tenk_word_counts(cik, f.accn, f.doc)
        if prev is not None and counts:
            rows.append(
                {"cik": _cik10(cik), "accn": f.accn, "filed": f.filed, "sim": cosine(counts, prev)}
            )
        if counts:
            prev = counts
    return pd.DataFrame(rows, columns=["cik", "accn", "filed", "sim"])


# ---------- quarter-by-quarter results (for the LLM scorer) ----------

QUARTER_FLOWS = {
    "revenue": [*FLOW_TAGS["revenue"], "RevenuesNetOfInterestExpense"],  # the last one: banks
    "cogs": FLOW_TAGS["cogs"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": FLOW_TAGS["net_income"],
}
BALANCE_TAGS = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "assets": STOCK_TAGS["assets"],
    "equity": STOCK_TAGS["equity"],
}
QUARTER_DAYS = (80, 100)


def _days(e: dict) -> int | None:
    if "start" not in e:
        return None
    return (pd.Timestamp(e["end"]) - pd.Timestamp(e["start"])).days


def _quarters_for_tag(gaap: dict, tag: str, asof: str) -> dict[str, tuple[str, float]]:
    """{quarter end: (filed, value)} for one tag, from 10-Qs and 10-Ks filed before `asof`.
    Each quarter keeps its FIRST reported value (later restatements are ignored). Fiscal Q4
    isn't reported on its own, so it's the annual value minus the year's three quarters."""
    ents = [
        e
        for e in gaap.get(tag, {}).get("units", {}).get("USD", [])
        if e["form"] in ("10-Q", "10-K") and e["filed"] < asof
    ]
    quarters: dict[str, tuple[str, float]] = {}
    annual: dict[tuple[str, str], tuple[str, float]] = {}
    for e in sorted(ents, key=lambda e: e["filed"]):
        d = _days(e)
        if d is None:
            continue
        if QUARTER_DAYS[0] <= d <= QUARTER_DAYS[1]:
            quarters.setdefault(e["end"], (e["filed"], float(e["val"])))
        elif ANNUAL_DAYS[0] <= d <= ANNUAL_DAYS[1]:
            annual.setdefault((e["start"], e["end"]), (e["filed"], float(e["val"])))
    for (start, end), (filed, val) in annual.items():
        if end in quarters:
            continue
        inside = [v for q_end, (_, v) in quarters.items() if start < q_end < end]
        if len(inside) == 3:
            quarters[end] = (filed, val - sum(inside))
    return quarters


def quarterly_table(facts: dict | None, asof: str, n: int = 8) -> pd.DataFrame:
    """The last `n` fiscal quarters known before `asof` (YYYY-MM-DD): revenue, gross profit,
    operating income and net income, plus revenue growth vs the same quarter a year earlier
    and margins. Values in USD; `filed` is when the quarter first became public."""
    gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    cols: dict[str, dict[str, float]] = {}
    filed: dict[str, str] = {}
    for field, tags in QUARTER_FLOWS.items():
        merged: dict[str, float] = {}
        for tag in tags:  # first tag with a value for that quarter wins
            for end, (f, v) in _quarters_for_tag(gaap, tag, asof).items():
                if end not in merged:
                    merged[end] = v
                    filed[end] = min(filed.get(end, f), f)
        cols[field] = merged
    df = pd.DataFrame(cols).reindex(columns=list(QUARTER_FLOWS))
    if df.empty:
        return df
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df["filed"] = pd.to_datetime([filed[d.strftime("%Y-%m-%d")] for d in df.index])
    df["gross_profit"] = df["gross_profit"].fillna(df["revenue"] - df["cogs"])
    ends = df.index.to_series()
    gap = (ends - ends.shift(4)).dt.days
    df["revenue_yoy"] = (df["revenue"] / df["revenue"].shift(4) - 1).where(gap.between(350, 380))
    df["gross_margin"] = df["gross_profit"] / df["revenue"]
    df["operating_margin"] = df["operating_income"] / df["revenue"]
    return df.drop(columns="cogs").tail(n)


def latest_balance(facts: dict | None, asof: str) -> dict[str, Any]:
    """Latest balance-sheet values from 10-Qs/10-Ks filed before `asof`, plus their date."""
    gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    out: dict[str, Any] = {}
    for field, tags in BALANCE_TAGS.items():
        for tag in tags:
            ents = [
                e
                for e in gaap.get(tag, {}).get("units", {}).get("USD", [])
                if e["form"] in ("10-Q", "10-K") and e["filed"] < asof and "start" not in e
            ]
            if ents:
                latest_end = max(e["end"] for e in ents)
                first = min((e for e in ents if e["end"] == latest_end), key=lambda e: e["filed"])
                out[field] = float(first["val"])
                out["as_of"] = max(out.get("as_of", ""), latest_end)
                break
    return out


_SPACES = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n\s*\n+")
_BREAKS = re.compile(r"<(br|/p|/div|/tr|/li|/h\d)[^>]*>", re.I)


def clean_text(raw_html: str) -> str:
    """Readable visible text of a filing (numbers and punctuation kept)."""
    text = _BREAKS.sub("\n", _BLOCKS.sub(" ", _HIDDEN.sub(" ", raw_html)))
    text = html.unescape(_TAGS.sub(" ", text)).replace("\xa0", " ")
    return _BLANKS.sub("\n\n", _SPACES.sub(" ", text)).strip()


def filing_text(cik: str | int, accn: str, doc: str) -> str:
    """Cached readable text of one filing's primary document."""
    path = sec_dir() / "text" / _cik10(cik) / f"{accn}.txt.gz"
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return f.read()
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/{doc}"
    body = _get(url)
    text = clean_text(body.decode("utf-8", errors="ignore")) if body else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(text)
    return text


_EX99 = re.compile(r"ex[-_]?99", re.I)


def earnings_release(
    subs: dict | None, cik: str | int, asof: str, max_age_days: int = 120
) -> dict | None:
    """The latest earnings press release (8-K item 2.02, exhibit 99) filed before `asof`.
    Results reach the 8-K weeks before the 10-Q, so this is the freshest quarter there is.
    Returns {"filed", "accn", "doc", "text"} or None."""
    if not subs:
        return None
    r = subs["filings"]["recent"]
    oldest = (pd.Timestamp(asof) - pd.Timedelta(max_age_days, "D")).strftime("%Y-%m-%d")
    hits = [
        i
        for i, (form, filed, items) in enumerate(
            zip(r["form"], r["filingDate"], r["items"], strict=True)
        )
        if form == "8-K" and "2.02" in (items or "") and oldest <= filed < asof
    ]
    if not hits:
        return None
    i = max(hits, key=lambda k: r["filingDate"][k])
    accn = r["accessionNumber"][i]
    folder = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}"
    path = sec_dir() / "index" / f"{accn}.json.gz"
    index = _cached_json(path, f"{folder}/index.json") or {}
    names = [f["name"] for f in index.get("directory", {}).get("item", [])]
    exhibits = sorted(
        n for n in names if _EX99.search(n) and n.lower().endswith((".htm", ".html", ".txt"))
    )
    if not exhibits:
        return None
    return {
        "filed": r["filingDate"][i],
        "accn": accn,
        "doc": exhibits[0],
        "text": filing_text(cik, accn, exhibits[0]),
    }


_MDNA = "management's discussion and analysis"
_MDNA_END = ("quantitative and qualitative disclosure", "controls and procedures")


def mdna_excerpt(text: str, max_chars: int = 15_000) -> tuple[str, bool]:
    """The start of the MD&A section, up to max_chars. Filings repeat the heading in the table
    of contents and cross-references, so the occurrence followed by the longest stretch before
    the next section is taken. Returns (excerpt, found); not found falls back to the opening."""
    low = text.lower().replace("’", "'")
    best, best_len, i = None, 0, low.find(_MDNA)
    while i != -1:
        ends = [j for j in (low.find(m, i + len(_MDNA)) for m in _MDNA_END) if j != -1]
        length = (min(ends) if ends else len(low)) - i
        if length > best_len:
            best, best_len = i, length
        i = low.find(_MDNA, i + 1)
    if best is None:
        return text[:max_chars], False
    return text[best : best + min(best_len, max_chars)], True


# ---------- universe + CLI ----------


def universe_ciks() -> list[str]:
    """Every CIK that was ever among the point-in-time 200 largest companies."""
    from horizon_trader.backtest import megacap as M

    caps = pd.read_parquet(data_dir() / "massive" / "reference" / "market_caps.parquet")
    out: set[str] = set()
    for _, g in caps.groupby("date"):
        top = M.top_n(g, 200).index
        out |= set(g.set_index("ticker").loc[top, "cik"].dropna().astype(str))
    return sorted(_cik10(c) for c in out if c.strip().isdigit())


def download(text: bool = True, threads: int = 8) -> None:
    ciks = universe_ciks()
    print(f"{len(ciks)} companies")

    def one(cik: str) -> tuple[str, int, int]:
        n10k = len(tenk_table(company_facts(cik)))
        docs = 0
        if text:
            docs = len(similarity_table(cik)) + 1
        return cik, n10k, docs

    done = 0
    with ThreadPoolExecutor(threads) as ex:
        for cik, n10k, docs in ex.map(one, ciks):
            done += 1
            if done % 25 == 0 or done == len(ciks):
                print(f"  {done}/{len(ciks)} (last CIK {cik}: {n10k} 10-K fact sets, {docs} texts)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("command", choices=["download", "check"])
    p.add_argument("--no-text", action="store_true", help="skip 10-K text (Lazy Prices)")
    args = p.parse_args()
    if args.command == "check":
        t = tenk_table(company_facts("320193"))
        print(t.tail(3).to_string())
        return
    download(text=not args.no_text)


if __name__ == "__main__":
    main()
