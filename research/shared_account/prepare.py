"""Freeze raw ETF actions and a compact minute panel; never edit original caches."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

from horizon_trader.config import data_dir, load_settings
from horizon_trader.datasources import massive

ROOT = Path(__file__).resolve().parents[2]
OUT = data_dir() / "shared_account_2026_10_01"
SETTINGS = ROOT / "research/portfolio_data_review_2026_10_01/results/effective_daily_settings.json"


def raw_actions():
    import yfinance as yf

    dest = OUT / "raw"
    dest.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(OUT / "yf-cache"))
    rows = []
    for ticker in load_settings(SETTINGS).universe:
        path = dest / f"{ticker}.parquet"
        old = data_dir() / "research_cycle_2026_10_01/raw" / path.name
        if not path.exists():
            if old.exists():
                frame = pd.read_parquet(old)
            else:
                frame = yf.download(
                    ticker,
                    period="max",
                    actions=True,
                    auto_adjust=False,
                    threads=False,
                    progress=False,
                )
                if isinstance(frame.columns, pd.MultiIndex):
                    frame = frame.xs(ticker, axis=1, level=1)
            if frame.empty or "Dividends" not in frame or "Stock Splits" not in frame:
                raise RuntimeError(f"Missing raw/actions for {ticker}")
            frame.to_parquet(path)
        rows.append({"symbol": ticker, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        print(f"raw/actions frozen: {ticker}", flush=True)
    (dest / "manifest.json").write_text(json.dumps(rows, indent=2))


def compact_minutes():
    symbols = load_settings(SETTINGS).universe
    candidates = pd.read_parquet(data_dir() / "massive/derived/orb5_stop1_trades.parquet")
    top = candidates[candidates["rank"].eq(1)].set_index("date").ticker.to_dict()
    folder = OUT / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    days = [d for d in massive.local_days() if date(2021, 10, 4) <= d <= date(2026, 9, 30)]

    def extract(day):
        path = folder / f"{day}.parquet"
        if path.exists():
            return
        tickers = sorted(set(symbols + [top.get(pd.Timestamp(day), "QQQ")]))
        frame = massive.load_day(day, tickers=tickers)
        clock = frame.ts.dt.hour * 60 + frame.ts.dt.minute
        frame = frame[clock.ge(570) & clock.lt(960)]
        frame.to_parquet(path, index=False)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, _ in enumerate(pool.map(extract, days), 1):
            if i % 100 == 0 or i == len(days):
                print(f"compact sessions: {i}/{len(days)}", flush=True)


def entitlement():
    from botocore.exceptions import ClientError

    client = massive.s3_client()
    results = []
    for day in [date(2017, 1, 3), date(2020, 3, 16)]:
        try:
            reply = client.head_object(Bucket=massive.BUCKET, Key=massive._key("minute", day))
            row = {"date": str(day), "accessible": True, "bytes": reply["ContentLength"]}
        except ClientError as exc:
            row = {"date": str(day), "accessible": False, "code": exc.response["Error"]["Code"]}
        results.append(row)
        print(json.dumps(row), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "older_entitlement.json").write_text(json.dumps(results, indent=2))


def dividend_dates():
    from horizon_trader.datasources.massive_ref import paginate

    dest = OUT / "dividend_dates"
    dest.mkdir(parents=True, exist_ok=True)
    for ticker in load_settings(SETTINGS).universe:
        path = dest / f"{ticker}.json"
        if not path.exists():
            rows = list(
                paginate(
                    "/v3/reference/dividends",
                    {
                        "ticker": ticker,
                        "ex_dividend_date.gte": "2007-01-01",
                        "limit": 1000,
                        "sort": "ex_dividend_date",
                        "order": "asc",
                    },
                )
            )
            path.write_text(json.dumps(rows, indent=2))
        print(f"dividend dates frozen: {ticker}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["raw", "minutes", "entitlement", "dividends"])
    args = parser.parse_args()
    {
        "raw": raw_actions,
        "minutes": compact_minutes,
        "entitlement": entitlement,
        "dividends": dividend_dates,
    }[args.action]()
