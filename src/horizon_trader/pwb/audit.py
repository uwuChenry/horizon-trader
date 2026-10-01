"""Audit the headline Sharpe ratios of Papers With Backtest from the NAV on each strategy page.

    uv run python -m horizon_trader.pwb.audit [--refresh]

Each paperswithbacktest.com/strategies/<slug> page embeds the strategy's NAV (about two points
a month, 1990 onward) and its current positions; the code and replication notes are paywalled.
For every strategy in the awesome-systematic-trading README table (61 rows) and the site's
top-ranked list page, this recomputes from month-end NAV:
  Sharpe rf=0     mean monthly return / std, annualised: the site's convention
  Sharpe excess   the same after subtracting the 3-month T-bill (FRED TB3MS). The site's NAV
                  earns interest on idle cash but its Sharpe doesn't subtract the risk-free
                  rate, so a strategy that sits mostly in cash scores well
  beta, corr      against the S&P 500 total return index
and flags what the positions give away (the universe the code really trades).
Pages are cached under <data_dir>/pwb/pages; --refresh downloads them again.
"""

from __future__ import annotations

import argparse
import html
import io
import re
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.config import REPO_ROOT, data_dir
from horizon_trader.datasources.store import load_bars

SITE = "https://paperswithbacktest.com/strategies"
README = (
    "https://raw.githubusercontent.com/paperswithbacktest/awesome-systematic-trading/main/README.md"
)
UA = {"User-Agent": "Mozilla/5.0"}
CRYPTO = {"BTC", "ETH", "LTC", "XRP", "DASH", "DOGE", "ADA", "BTCUSD_D1"}
NOT_STRATEGIES = {"still-working", "awaiting-data", "dataset"}


def _cache() -> Path:
    path = data_dir() / "pwb" / "pages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get(url: str, path: Path, refresh: bool) -> str:
    if refresh or not path.exists():
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as resp:
            path.write_bytes(resp.read())
        time.sleep(0.5)  # be polite to the site
    return path.read_text(encoding="utf8", errors="replace")


def fetch_page(slug: str, refresh: bool = False) -> str:
    return _get(f"{SITE}/{slug}", _cache() / f"{slug}.html", refresh)


# ---------------------------------------------------------------- parsing


def parse_nav(page: str) -> pd.Series:
    """The {date, value} points the page's equity chart is drawn from."""
    pts = re.findall(r'\{\\"date\\":\\"(\d{4}-\d\d-\d\d)[^}]*?\\"value\\":([\d.eE+-]+)\}', page)
    nav = pd.Series(
        [float(v) for _, v in pts], index=pd.to_datetime([d for d, _ in pts]), dtype=float
    )
    return nav[~nav.index.duplicated()].sort_index()


def parse_positions(page: str) -> list[tuple[str, float]]:
    pos = re.findall(r'\\"ticker\\":\\"([^\\]+)\\",\\"position\\":(-?[\d.eE+-]+)', page)
    return [(t, float(q)) for t, q in pos]


def parse_page_metrics(page: str) -> dict[str, float]:
    """The site's own numbers for this page (full backtest)."""
    out = {}
    for key in ("sharpeRatio", "annualReturn", "annualVolatility", "maxDrawdown"):
        m = re.search(rf'\\"{key}\\":(-?[\d.eE+-]+)', page)
        out[key] = float(m.group(1)) if m else np.nan
    return out


def parse_published(page: str) -> str | None:
    text = html.unescape(
        re.sub(r"<[^>]+>", "\n", re.sub(r"<script.*?</script>", "", page, flags=re.S))
    )
    m = re.search(r"Published\n+([^\n]+)", text)
    return m.group(1).strip() if m else None


def readme_table(text: str) -> pd.DataFrame:
    """Rows of the README's generated strategy table."""
    rows = re.findall(
        r"\| \[([^\]]+)\]\(https://paperswithbacktest\.com/strategies/([a-z0-9-]+)\) \| `([\d.-]+)`"
        r" \| `([\d.-]+)` \| `([\d.]+)%` \| `(\d+)` \|",
        text,
    )
    cols = ["title", "slug", "readme Sharpe", "readme t", "readme vol %", "readme years"]
    df = pd.DataFrame(rows, columns=cols)
    for c in cols[2:]:
        df[c] = df[c].astype(float)
    return df


def listing(page: str) -> pd.DataFrame:
    """Slug and headline Sharpe of each card on a strategies list page, in page order."""
    slugs = [
        s for s in re.findall(r'href="/strategies/([a-z0-9-]+)"', page) if s not in NOT_STRATEGIES
    ]
    text = html.unescape(
        re.sub(r"<[^>]+>", "\n", re.sub(r"<script.*?</script>", "", page, flags=re.S))
    )
    sharpes = re.findall(r"\n\s*(-?[\d.,]+)\s*\n\s*(?:OOS )?Sharpe Ratio", text)
    slugs = list(dict.fromkeys(slugs))
    n = min(len(slugs), len(sharpes))
    return pd.DataFrame(
        {"slug": slugs[:n], "list Sharpe": [float(s.replace(",", "")) for s in sharpes[:n]]}
    )


# ---------------------------------------------------------------- metrics


def tbill_monthly() -> pd.Series:
    """3-month T-bill yield (FRED TB3MS) as a monthly return, indexed at month end."""
    path = data_dir() / "reference" / "tb3ms.parquet"
    if not path.exists() or time.time() - path.stat().st_mtime > 86_400:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=TB3MS"
        with urllib.request.urlopen(url, timeout=60) as resp:
            df = pd.read_csv(io.BytesIO(resp.read()), parse_dates=["observation_date"])
        path.parent.mkdir(parents=True, exist_ok=True)
        df.set_index("observation_date")[["TB3MS"]].to_parquet(path)
    tb = pd.read_parquet(path)["TB3MS"]
    return (tb / 100 / 12).resample("ME").last()


def nav_stats(nav: pd.Series, rf: pd.Series, market: pd.Series) -> dict[str, float]:
    """Stats from month-end NAV. `rf` and `market` are monthly returns at month end."""
    m = nav.resample("ME").last().pct_change().dropna()
    rf = rf.reindex(m.index).ffill().fillna(0.0)
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    vol = m.std() * np.sqrt(12)
    mk = market.reindex(m.index)
    ok = mk.notna()
    beta = m[ok].cov(mk[ok]) / mk[ok].var() if ok.sum() > 12 else np.nan
    return {
        "CAGR": (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1,
        "vol": vol,
        "Sharpe rf=0": m.mean() * 12 / vol if vol else np.nan,
        "Sharpe excess": (m - rf).mean() * 12 / vol if vol else np.nan,
        "T-bill share of return": rf.mean() / m.mean() if m.mean() > 0 else np.nan,
        "beta": beta,
        "corr": m[ok].corr(mk[ok]) if ok.sum() > 12 else np.nan,
        "start": nav.index[0],
    }


def flags(positions: list[tuple[str, float]], stats: dict, published: str | None) -> list[str]:
    """What the positions and NAV give away about the code behind a row."""
    tickers = {t for t, _ in positions}
    out = []
    if len(tickers) >= 400 and {"ABNB", "AAPL"} <= tickers and stats["start"].year < 2000:
        out.append("today's S&P 500 from 1990 (survivorship)")
    if tickers and tickers <= {"SPX", "SPY"} and stats["corr"] > 0.9:
        out.append("holds only the index (corr > 0.9)")
    crypto = tickers & CRYPTO  # a crypto book, not a stock list that happens to hold DASH
    if crypto and len(crypto) >= len(tickers) / 4 and stats["start"].year < 2009:
        out.append("crypto NAV starts before Bitcoin existed")
    if stats["Sharpe rf=0"] > 0.8 and stats["Sharpe excess"] < 0.6 * stats["Sharpe rf=0"]:
        out.append("mostly T-bill interest")
    return out


def audit(refresh: bool = False) -> pd.DataFrame:
    readme = readme_table(_get(README, _cache() / "README.md", refresh))
    lst = listing(_get(SITE, _cache() / "_list.html", refresh))
    slugs = list(dict.fromkeys(list(readme["slug"]) + list(lst["slug"])))
    rf = tbill_monthly()
    spx = load_bars(["^SP500TR"])["close"]["^SP500TR"]
    market = spx.resample("ME").last().pct_change()
    rows = []
    for slug in slugs:
        page = fetch_page(slug, refresh)
        nav = parse_nav(page)
        if len(nav) < 24:
            continue
        s = nav_stats(nav, rf, market)
        pos = parse_positions(page)
        pub = parse_published(page)
        title = re.search(r"<title>([^<]+)</title>", page)
        rows.append(
            {
                "slug": slug,
                "title": html.unescape(title.group(1)).split(" - Papers With Backtest")[0]
                if title
                else slug,
                "published": pub,
                "page Sharpe": parse_page_metrics(page)["sharpeRatio"],
                **s,
                "positions": len(pos),
                "tickers": " ".join(t for t, _ in pos[:6]),
                "flags": "; ".join(flags(pos, s, pub)),
            }
        )
    df = pd.DataFrame(rows)
    df = df.merge(readme[["slug", "readme Sharpe", "readme vol %"]], on="slug", how="left")
    df = df.merge(lst, on="slug", how="left")
    return df


def summary(df: pd.DataFrame) -> pd.DataFrame:
    """Medians and counts, README rows vs the whole audited set."""
    groups = {"README table": df[df["readme Sharpe"].notna()], "all audited": df}
    out = {}
    for name, g in groups.items():
        out[name] = {
            "strategies": len(g),
            "median headline Sharpe": g["readme Sharpe"].fillna(g["list Sharpe"]).median(),
            "median Sharpe rf=0 (NAV)": g["Sharpe rf=0"].median(),
            "median Sharpe excess of T-bills": g["Sharpe excess"].median(),
            "share > 1.0, rf=0": (g["Sharpe rf=0"] > 1).mean(),
            "share > 1.0, excess": (g["Sharpe excess"] > 1).mean(),
            "README vs page NAV off by > 0.5": (
                (g["readme Sharpe"] - g["Sharpe rf=0"]).abs() > 0.5
            ).sum(),
            "flag: survivorship (today's S&P 500)": g["flags"].str.contains("survivorship").sum(),
            "flag: only holds the index": g["flags"].str.contains("only the index").sum(),
            "flag: mostly T-bill interest": g["flags"].str.contains("T-bill").sum(),
        }
    return pd.DataFrame(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="download the pages again")
    args = ap.parse_args()
    pd.set_option("display.width", 250, "display.max_colwidth", 48, "display.max_rows", 200)
    df = audit(args.refresh)
    out = data_dir() / "pwb" / "audit.csv"
    df.to_csv(out, index=False)
    show = df.assign(
        title=df["title"].str.slice(0, 48),
        headline=df["readme Sharpe"].fillna(df["list Sharpe"]),
        CAGR=df["CAGR"].map("{:+.1%}".format),
        vol=df["vol"].map("{:.1%}".format),
    )[
        [
            "title",
            "headline",
            "page Sharpe",
            "Sharpe rf=0",
            "Sharpe excess",
            "CAGR",
            "vol",
            "beta",
            "corr",
            "flags",
        ]
    ].sort_values("headline", ascending=False)
    print(show.round(2).to_string(index=False))
    print("\n" + summary(df).round(2).to_string())
    print(f"\nwritten {out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out}")


if __name__ == "__main__":
    main()
