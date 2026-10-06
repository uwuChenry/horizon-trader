"""Forward check of IBKR's scanners as ORB's live stock picker (option 3 in orb_shortlist.py).

    uv run python -m horizon_trader.intraday.scanner_log capture   # run before 9:25 ET; exits ~9:36
    uv run python -m horizon_trader.intraday.scanner_log compare   # after Massive has that day

`capture` waits for 9:25 and 9:35:05 New York time and saves each scanner's list (max 50 rows)
to data/live/scanner/<date>.json. Read-only: no orders. `compare` takes every logged day that
the Massive minute and day files now cover, finds the full-market ORB top-1 exactly as the
backtest does (orb.build_trades), and reports whether each scanner's list contained it.
orb_shortlist.py approximates the 9:35 volume scan from history; this measures the real one.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace

import pandas as pd

from horizon_trader.config import data_dir

NY = "America/New_York"
FILTERS = {"priceAbove": "5", "avgVolumeAbove": "1000000"}  # ORB's own filters (ATR: ours)
SCANS = {
    "09:25": [  # pre-market: candidates for option 1 from IBKR itself
        ("MOST_ACTIVE", "CORP"),
        ("HOT_BY_VOLUME", "CORP"),
        ("TOP_PERC_GAIN", "CORP"),  # the open-gap scans return nothing before 9:30
        ("TOP_PERC_LOSE", "CORP"),
        ("SCAN_stVolumeVsAvg5min_DESC", "CORP"),
    ],
    "09:35:05": [  # just after the 5-minute opening range closes
        ("SCAN_stVolumeVsAvg5min_DESC", "CORP"),
        ("SCAN_stVolumeVsAvg5min_DESC", "ALL"),
        ("HOT_BY_VOLUME", "CORP"),
    ],
}


def log_dir():
    path = data_dir() / "live" / "scanner"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_scan(ib, code: str, stock_type: str) -> list[str]:
    from ib_async import ScannerSubscription, TagValue

    sub = ScannerSubscription(
        instrument="STK",
        locationCode="STK.US.MAJOR",
        scanCode=code,
        numberOfRows=50,
        stockTypeFilter=stock_type,
    )
    rows = ib.reqScannerData(sub, [], [TagValue(k, v) for k, v in FILTERS.items()])
    return [r.contractDetails.contract.symbol for r in sorted(rows, key=lambda r: r.rank)]


def massive_snapshot() -> dict:
    """Massive's full-market snapshot (Starter plan, 15-minute delay): does it carry
    pre-market data? Keeps a summary and the 100 names with the most volume today."""
    import os
    import urllib.request

    url = "https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {os.environ['MASSIVE_API_KEY']}"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        tickers = json.loads(r.read())["tickers"]
    vol = {t["ticker"]: max(t["day"]["v"], t["min"].get("av", 0)) for t in tickers}
    latest = max(t.get("updated", 0) for t in tickers)
    return {
        "captured": pd.Timestamp.now(tz=NY).isoformat(),
        "tickers": len(tickers),
        "with_volume_today": sum(v > 0 for v in vol.values()),
        "latest_update": str(pd.Timestamp(latest, unit="ns", tz="UTC").tz_convert(NY)),
        "symbols": [k for k, v in sorted(vol.items(), key=lambda kv: -kv[1])[:100] if v > 0],
    }


def capture() -> None:
    from horizon_trader.execution.ibkr import connect

    today = pd.Timestamp.now(tz=NY).strftime("%Y-%m-%d")
    path = log_dir() / f"{today}.json"
    log = json.loads(path.read_text()) if path.exists() else {}
    for at, scans in SCANS.items():
        when = pd.Timestamp(f"{today} {at}", tz=NY)
        wait = (when - pd.Timestamp.now(tz=NY)).total_seconds()
        if wait < -120:
            print(f"{at} already passed; skipping")
            continue
        if wait > 0:
            print(f"waiting {wait / 60:.0f} min for {at} ET", flush=True)
            time.sleep(wait)
        ib = connect(readonly=True, client_id=11)
        try:
            ib.RequestTimeout = 30
            for code, stock_type in scans:
                key = f"{at} {code} {stock_type}"
                try:
                    symbols = run_scan(ib, code, stock_type)
                except Exception as e:  # keep the other scans
                    symbols, key = [], key + f" ERROR {e!r}"
                log[key] = {"captured": pd.Timestamp.now(tz=NY).isoformat(), "symbols": symbols}
                print(f"{key}: {len(symbols)} rows, top 5 {symbols[:5]}", flush=True)
        finally:
            ib.disconnect()
        if at == "09:25":
            try:
                import horizon_trader.config  # noqa: F401  (loads MASSIVE_API_KEY from .env)

                log[f"{at} massive_snapshot"] = snap = massive_snapshot()
                print(
                    f"massive snapshot: {snap['with_volume_today']} of {snap['tickers']} "
                    f"tickers traded today, latest update {snap['latest_update']}",
                    flush=True,
                )
            except Exception as e:
                log[f"{at} massive_snapshot ERROR {e!r}"] = {"symbols": []}
        path.write_text(json.dumps(log, indent=1))
    print("saved", path)


def compare() -> pd.DataFrame:
    from horizon_trader.intraday import orb

    trades = orb.build_trades(replace(orb.RULES, stop_atr=1.0))
    top = trades[trades["rank"] <= 5]
    rows = []
    for path in sorted(log_dir().glob("*.json")):
        day = pd.Timestamp(path.stem)
        picks = top[top["date"] == day].sort_values("rank")["ticker"].tolist()
        if not picks:
            print(f"{path.stem}: no Massive data yet (download it, then rerun)")
            continue
        for key, entry in json.loads(path.read_text()).items():
            symbols = entry["symbols"]
            rows.append(
                {
                    "date": path.stem,
                    "scan": key,
                    "top1": picks[0],
                    "top1 in list": picks[0] in symbols,
                    "top1 rank in list": symbols.index(picks[0]) + 1
                    if picks[0] in symbols
                    else None,
                    "top5 found": sum(p in symbols for p in picks),
                }
            )
    table = pd.DataFrame(rows)
    if len(table):
        print(table.to_string(index=False))
        print("\nshare of days with the top-1 in the list, per scan:")
        print(table.groupby("scan")["top1 in list"].mean().map("{:.0%}".format).to_string())
    return table


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("action", choices=("capture", "compare"))
    args = p.parse_args()
    capture() if args.action == "capture" else compare()


if __name__ == "__main__":
    main()
