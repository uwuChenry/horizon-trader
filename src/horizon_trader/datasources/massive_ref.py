"""Massive REST reference data: stock splits and the common-stock ticker list.

    uv run python -m horizon_trader.datasources.massive_ref

Reads MASSIVE_API_KEY from .env. Saves <data_dir>/massive/reference/{splits,tickers}.parquet.
Splits are needed because the flat files are unadjusted: without them, a 10-for-1 split looks
like a 10x volume spike. The ticker list (active and delisted) filters the flat files down to
common stocks, dropping ETFs, warrants, units, preferreds and rights.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pandas as pd

from horizon_trader.config import data_dir

API = "https://api.massive.com"
COMMON_TYPES = ("CS",)  # common stock. ADRC (ADR common) is left out, as CRSP codes 10/11 do

Fetch = Callable[[str], dict[str, Any]]


def _http_get(url: str) -> dict[str, Any]:
    import horizon_trader.config  # noqa: F401  (loads .env)

    key = os.environ.get("MASSIVE_API_KEY")
    if not key:
        raise SystemExit("Set MASSIVE_API_KEY in .env (Massive dashboard -> Keys).")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            time.sleep(2**attempt)  # rate limit or server hiccup: back off and retry
    raise RuntimeError(f"giving up on {url}")


def paginate(path: str, params: dict[str, Any], fetch: Fetch = _http_get) -> Iterator[dict]:
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    while url:
        page = fetch(url)
        yield from page.get("results", [])
        url = page.get("next_url")


def fetch_splits(since: str = "2000-01-01", fetch: Fetch = _http_get) -> pd.DataFrame:
    params = {"execution_date.gte": since, "limit": 5000, "sort": "execution_date.asc"}
    rows = list(paginate("/stocks/v1/splits", params, fetch))
    cols = ["ticker", "execution_date", "split_from", "split_to", "adjustment_type"]
    df = pd.DataFrame(rows, columns=cols)
    df["execution_date"] = pd.to_datetime(df["execution_date"])
    return df.sort_values(["ticker", "execution_date"], ignore_index=True)


def fetch_tickers(types: tuple[str, ...] = COMMON_TYPES, fetch: Fetch = _http_get) -> pd.DataFrame:
    rows = []
    for type_ in types:
        for active in ("true", "false"):  # delisted names too, or the universe has survivor bias
            params = {"market": "stocks", "type": type_, "active": active, "limit": 1000}
            rows += list(paginate("/v3/reference/tickers", params, fetch))
    cols = ["ticker", "type", "active", "name", "primary_exchange", "delisted_utc"]
    return pd.DataFrame(rows).reindex(columns=cols).drop_duplicates(ignore_index=True)


def ref_path(name: str) -> Path:
    return data_dir() / "massive" / "reference" / f"{name}.parquet"


def load_splits() -> pd.DataFrame:
    return pd.read_parquet(ref_path("splits"))


def load_common_tickers() -> set[str]:
    return set(pd.read_parquet(ref_path("tickers"))["ticker"])


def main() -> None:
    ref_path("x").parent.mkdir(parents=True, exist_ok=True)
    splits = fetch_splits()
    splits.to_parquet(ref_path("splits"), index=False)
    print(f"splits: {len(splits):,} events, {splits.execution_date.min():%Y-%m-%d} .. "
          f"{splits.execution_date.max():%Y-%m-%d}")  # fmt: skip
    tickers = fetch_tickers()
    tickers.to_parquet(ref_path("tickers"), index=False)
    n_active = int(tickers["active"].sum())
    n_gone = len(tickers) - n_active
    print(f"common stocks: {len(tickers):,} ({n_active:,} active, {n_gone:,} delisted)")


if __name__ == "__main__":
    main()
