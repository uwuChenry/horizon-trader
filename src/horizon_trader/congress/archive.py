"""STOCK Act trade disclosures by members of Congress (and senior executive officials).

    uv run python -m horizon_trader.congress.archive [--ref <commit>]

Source: github.com/kadoa-org/congress-trading-monitor (MIT), which parses the House Clerk's
periodic transaction reports, the Senate eFD system and OGE filings into one JSON file per
filer (public/data/filer/*.json), 2012 to today. Every trade has both dates that matter:
  transaction_date  when the member traded (the date most "Pelosi tracker" backtests use)
  filing_date       when the trade became public, up to 45 days later (the STOCK Act limit;
                    late filings exist). A copy-trader can only act after this date.
Amounts are ranges ($1,001-$15,000 ... $5M+), not exact. Saved under
<data_dir>/congress/: filers/*.json as downloaded, trades.parquet, source.json.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from horizon_trader.config import data_dir

REPO = "kadoa-org/congress-trading-monitor"
PINNED_REF = "ef9e1cf70e694c790cb6580034ad357ca740b4b8"  # daily refresh of 2026-09-27
FILER_DIR = "public/data/filer/"


def root() -> Path:
    return data_dir() / "congress"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "horizon-trader research"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def filer_paths(ref: str) -> list[str]:
    tree = json.loads(_get(f"https://api.github.com/repos/{REPO}/git/trees/{ref}?recursive=1"))
    return [
        t["path"]
        for t in tree["tree"]
        if t["path"].startswith(FILER_DIR) and t["path"].endswith(".json")
    ]


def download(ref: str = PINNED_REF, threads: int = 8) -> Path:
    out = root() / "filers" / ref[:12]
    out.mkdir(parents=True, exist_ok=True)
    todo = [p for p in filer_paths(ref) if not (out / Path(p).name).exists()]

    def fetch(p: str) -> None:
        url = f"https://raw.githubusercontent.com/{REPO}/{ref}/{p}"
        (out / Path(p).name).write_bytes(_get(url))

    with ThreadPoolExecutor(threads) as pool:
        list(pool.map(fetch, todo))
    source = {"repo": REPO, "ref": ref, "downloaded": datetime.now(UTC).isoformat()}
    (root() / "source.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
    return out


COLS = [
    "id",
    "filer_id",
    "filer_name",
    "chamber",
    "party",
    "branch",
    "owner",
    "ticker",
    "asset_name",
    "asset_type",
    "transaction_type",
    "transaction_date",
    "filing_date",
    "days_to_file",
    "is_late",
    "amount_range_low",
    "amount_range_high",
    "doc_url",
]


def parse(folder: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(folder.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        filer = d.get("filer") or {}  # chamber / party / branch live here, not on each trade
        meta = {
            "filer_name": filer.get("full_name"),
            "chamber": filer.get("chamber"),
            "party": filer.get("party"),
            "branch": filer.get("branch"),
        }
        rows += [t | meta for t in d.get("trades", [])]
    df = pd.DataFrame(rows).reindex(columns=COLS).drop_duplicates("id")
    for c in ("transaction_date", "filing_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["ticker"] = df["ticker"].str.upper().str.strip()
    return df.sort_values("filing_date", ignore_index=True)


def build(ref: str = PINNED_REF) -> pd.DataFrame:
    df = parse(download(ref))
    df.to_parquet(root() / "trades.parquet", index=False)
    return df


def load() -> pd.DataFrame:
    path = root() / "trades.parquet"
    return pd.read_parquet(path) if path.exists() else build()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--ref", default=PINNED_REF)
    args = p.parse_args()
    df = build(args.ref)
    print(
        f"{len(df):,} trades by {df['filer_id'].nunique()} filers, "
        f"filed {df['filing_date'].min():%Y-%m-%d} .. {df['filing_date'].max():%Y-%m-%d}"
    )
    print(df["transaction_type"].value_counts().head(8).to_string())
    print(df["asset_type"].value_counts().head(10).to_string())
    lag = (df["filing_date"] - df["transaction_date"]).dt.days
    print(
        f"days from trade to disclosure: median {lag.median():.0f}, "
        f"p90 {lag.quantile(0.9):.0f}, late (>45) {(lag > 45).mean():.0%}"
    )


if __name__ == "__main__":
    main()
