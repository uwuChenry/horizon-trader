"""Massive (formerly Polygon.io) flat-file downloader: whole-market US stock bars, one file per day.

    uv run python -m horizon_trader.datasources.massive check
    uv run python -m horizon_trader.datasources.massive download [--dataset minute|day]

Reads MASSIVE_S3_ACCESS_KEY / MASSIVE_S3_SECRET_KEY from .env (the S3 keys on the Massive
dashboard, not the REST API key). Each trading day is stored as
<data_dir>/massive/<dataset>/<YYYY>/<YYYY-MM-DD>.parquet with every ticker that traded that
day, delisted names included. Prices are NOT split-adjusted. Timestamps are bar starts in
America/New_York. Re-running skips days already on disk, so an interrupted download resumes.

License: Massive's individual plans are personal use only, and its market-data terms require
deleting the data if the account is terminated. Never commit or share these files.
"""

from __future__ import annotations

import argparse
import io
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from horizon_trader.config import data_dir

ENDPOINT = "https://files.massive.com"
BUCKET = "flatfiles"
DATASETS = {"minute": "minute_aggs_v1", "day": "day_aggs_v1"}
PLAN_YEARS = 5  # Stocks Starter history
TZ = "America/New_York"


def s3_client() -> Any:
    import boto3
    from botocore.config import Config

    import horizon_trader.config  # noqa: F401  (loads .env)

    key, secret = os.environ.get("MASSIVE_S3_ACCESS_KEY"), os.environ.get("MASSIVE_S3_SECRET_KEY")
    if not key or not secret:
        raise SystemExit(
            "Set MASSIVE_S3_ACCESS_KEY and MASSIVE_S3_SECRET_KEY in .env "
            "(dashboard -> Keys -> Flat Files / S3 credentials)."
        )
    return boto3.Session(aws_access_key_id=key, aws_secret_access_key=secret).client(
        "s3",
        endpoint_url=ENDPOINT,
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
    )


def _key(dataset: str, day: date) -> str:
    return f"us_stocks_sip/{DATASETS[dataset]}/{day:%Y/%m}/{day:%Y-%m-%d}.csv.gz"


def local_path(dataset: str, day: date) -> Path:
    return data_dir() / "massive" / dataset / f"{day:%Y}" / f"{day:%Y-%m-%d}.parquet"


def remote_days(client: Any, dataset: str, start: date, end: date) -> list[date]:
    """Trading days with a file on the server between start and end (inclusive)."""
    days = []
    for year in range(start.year, end.year + 1):
        prefix = f"us_stocks_sip/{DATASETS[dataset]}/{year}/"
        token = None
        while True:
            kwargs = {"Bucket": BUCKET, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = client.list_objects_v2(**kwargs)
            for obj in page.get("Contents", []):
                name = obj["Key"].rsplit("/", 1)[-1]
                if name.endswith(".csv.gz"):
                    day = date.fromisoformat(name.removesuffix(".csv.gz"))
                    if start <= day <= end:
                        days.append(day)
            if not page.get("IsTruncated"):
                break
            token = page["NextContinuationToken"]
    return sorted(days)


def parse_csv(raw: bytes) -> pd.DataFrame:
    """Flat-file CSV (gzip) -> tidy frame: ts (NY time, bar start), ticker, OHLCV, transactions."""
    df = pd.read_csv(io.BytesIO(raw), compression="gzip", keep_default_na=False, na_values=[""])
    df = df.dropna(subset=["ticker"])  # never drop a ticker literally named "NA"
    ts = pd.to_datetime(df.pop("window_start"), unit="ns", utc=True).dt.tz_convert(TZ)
    df.insert(0, "ts", ts)
    cols = ["ts", "ticker", "open", "high", "low", "close", "volume", "transactions"]
    return df[cols].sort_values(["ticker", "ts"], ignore_index=True)


def download_day(client: Any, dataset: str, day: date) -> Path:
    raw = client.get_object(Bucket=BUCKET, Key=_key(dataset, day))["Body"].read()
    path = local_path(dataset, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    parse_csv(raw).to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(path)  # atomic: a crash never leaves a half-written day behind
    return path


def download(
    client: Any, dataset: str, start: date, end: date, workers: int = 4
) -> tuple[list[date], dict[date, str]]:
    """Fetch every missing day in [start, end]. Returns (downloaded, {day: error})."""
    todo = [
        d for d in remote_days(client, dataset, start, end) if not local_path(dataset, d).exists()
    ]
    done, failed = [], {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_day, client, dataset, d): d for d in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            day = futures[fut]
            try:
                fut.result()
                done.append(day)
            except Exception as e:  # noqa: BLE001  (report and keep going; rerun retries)
                failed[day] = repr(e)
            if i % 20 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} days ({len(failed)} failed)", flush=True)
    return sorted(done), failed


def local_days(dataset: str = "minute") -> list[date]:
    root = data_dir() / "massive" / dataset
    return sorted(date.fromisoformat(p.stem) for p in root.glob("*/*.parquet"))


def load_day(day: date, dataset: str = "minute", tickers: list[str] | None = None) -> pd.DataFrame:
    filters = [("ticker", "in", tickers)] if tickers else None
    return pd.read_parquet(local_path(dataset, day), filters=filters)


def _check(client: Any) -> None:
    end = date.today()
    for dataset in DATASETS:
        days = remote_days(client, dataset, end - timedelta(days=14), end)
        latest = days[-1] if days else "-"
        print(f"{dataset:<6} files in the last 14 days: {len(days)} (latest {latest})")
    if days:
        df = parse_csv(client.get_object(Bucket=BUCKET, Key=_key("day", days[-1]))["Body"].read())
        print(
            f"day file {days[-1]}: {len(df):,} tickers, e.g.\n{df.head(3).to_string(index=False)}"
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="verify credentials and show what the server has")
    d = sub.add_parser("download", help="download missing days")
    d.add_argument("--dataset", choices=list(DATASETS), default="minute")
    default_start = date.today() - timedelta(days=365 * PLAN_YEARS - 7)  # inside the plan window
    d.add_argument("--start", type=date.fromisoformat, default=default_start)
    d.add_argument("--end", type=date.fromisoformat, default=date.today())
    d.add_argument("--workers", type=int, default=4)
    args = p.parse_args()

    client = s3_client()
    if args.cmd == "check":
        _check(client)
        return
    print(f"downloading {args.dataset} bars {args.start} .. {args.end}")
    done, failed = download(client, args.dataset, args.start, args.end, args.workers)
    print(f"downloaded {len(done)} days, {len(local_days(args.dataset))} on disk")
    if failed:
        print(f"{len(failed)} failed (rerun to retry):")
        for day, err in sorted(failed.items())[:10]:
            print(f"  {day}: {err}")


if __name__ == "__main__":
    main()
