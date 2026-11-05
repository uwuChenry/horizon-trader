"""Read-only metadata inventory; never invokes data providers or a broker.

Run: .venv/Scripts/python.exe research/portfolio_data_review_2026_10_01/inventory.py
Writes aggregate metadata only beside this script. No account IDs or credentials.
"""

from __future__ import annotations

import gzip
import json
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUTPUT = Path(__file__).resolve().parent / "inventory.json"


def range_of(values) -> dict:
    values = [str(x) for x in values if pd.notna(x) and str(x)]
    return {"first": min(values), "last": max(values)} if values else {}


def files_under(relative: str) -> dict:
    files = [p for p in (DATA / relative).rglob("*") if p.is_file()]
    return {"files": len(files), "bytes": sum(p.stat().st_size for p in files)}


def parquet_summary(relative: str, date_columns: tuple[str, ...] = ()) -> dict:
    path = DATA / relative
    if not path.exists():
        return {"exists": False}
    frame = pd.read_parquet(path)
    out = {"rows": len(frame), "columns": frame.columns.tolist()}
    if isinstance(frame.index, pd.DatetimeIndex):
        out["index_range"] = range_of(frame.index)
    out["date_ranges"] = {c: range_of(frame[c]) for c in date_columns if c in frame}
    return out


def supplemental(out: dict) -> None:
    """Cheap final metadata enrichment, also usable on an already completed inventory."""
    out["other_datasets"]["congress"] = parquet_summary(
        "congress/trades.parquet", ("transaction_date", "filing_date")
    )
    for day in out["llm_scores"]:
        out["llm_scores"][day] = parquet_summary(
            f"llm/fundamental_scores/{day}/scores.parquet", ("asof", "universe_date", "scored_at")
        )
    disk = shutil.disk_usage(ROOT)
    out["storage_planning"] = {
        "workspace_drive_free_bytes": disk.free,
        "five_more_years_minute_bytes_at_observed_rate": out["storage"]["massive/minute"]["bytes"],
        "estimate_caveat": (
            "Extrapolation from local compressed cache; historical volume can differ"
        ),
        "point_in_time_backfill": (
            "Older bars require separate historical month-end caps/CIKs, split coverage, "
            "and identifier/delisting validation; they do not extend current PIT data by themselves"
        ),
    }


def write_outputs(out: dict) -> None:
    OUTPUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    rows = [
        {"dataset": name, "files": val["files"], "bytes": val["bytes"]}
        for name, val in out["storage"].items()
    ]
    pd.DataFrame(rows).to_csv(OUTPUT.with_name("storage_inventory.csv"), index=False)


def main() -> None:
    out = {"audited_utc": pd.Timestamp.now(tz="UTC").isoformat(), "offline_only": True}
    out["storage"] = {
        name: files_under(name)
        for name in [
            "bars",
            "massive/day",
            "massive/minute",
            "massive/seconds",
            "sec/companyfacts",
            "sec/submissions",
            "sec/tenk",
            "sec/text",
            "sec/index",
            "live",
            "llm/fundamental_scores",
            "congress",
            "social",
            "pwb",
            "reference",
        ]
    }
    bars = []
    for p in sorted((DATA / "bars").glob("*.parquet")):
        frame = pd.read_parquet(p)
        bars.append({"symbol": p.stem, "rows": len(frame), **range_of(frame.index)})
    out["daily_adjusted_bars"] = {
        "symbols": len(bars),
        "individual_coverage": bars,
        "source": "Yahoo adjusted OHLCV; current-stock cache is not a historical universe",
    }
    out["massive_files"] = {
        kind: {
            "days": len(files := sorted((DATA / "massive" / kind).glob("*/*.parquet"))),
            **range_of([p.stem for p in files]),
        }
        for kind in ("day", "minute")
    }
    caps = pd.read_parquet(DATA / "massive/reference/market_caps.parquet")
    grouped = caps.groupby("date").size()
    out["point_in_time_caps"] = {
        "rows": len(caps),
        "dates": int(caps.date.nunique()),
        **range_of(caps.date),
        "tickers": int(caps.ticker.nunique()),
        "ciks": int(caps.cik.nunique()),
        "rows_per_date_min": int(grouped.min()),
        "rows_per_date_max": int(grouped.max()),
        "missing_market_caps": int(caps.market_cap.isna().sum()),
        "missing_ciks": int(caps.cik.isna().sum()),
        "columns": caps.columns.tolist(),
    }
    seconds = sorted((DATA / "massive/seconds").glob("*/*.parquet"))
    sec_rows, sec_empty, schemas = 0, 0, Counter()
    for p in seconds:
        metadata = pq.read_metadata(p)
        sec_rows += metadata.num_rows
        sec_empty += metadata.num_rows == 0
        schemas[tuple(metadata.schema.names)] += 1
    out["second_bars"] = {
        "minute_windows": len(seconds),
        "rows": sec_rows,
        "empty_windows": sec_empty,
        "dates": len({p.parent.name for p in seconds}),
        "tickers": len({p.stem.rsplit("_", 1)[0] for p in seconds}),
        **range_of([p.parent.name for p in seconds]),
        "schemas": [{"columns": list(k), "files": v} for k, v in schemas.items()],
        "sampling": "selected ORB entry/stop minutes, not full-market or full-session coverage",
        "contains_quotes": False,
    }
    all_filings, accession_lookup = [], {}
    submissions = list((DATA / "sec/submissions").glob("*.json.gz"))
    for p in submissions:
        with gzip.open(p, "rt", encoding="utf-8") as handle:
            data = json.load(handle)
        recent = data.get("filings", {}).get("recent", {})
        n = len(recent.get("form", []))
        for i in range(n):
            row = {
                k: recent.get(k, [None] * n)[i]
                for k in ("form", "filingDate", "acceptanceDateTime", "items", "accessionNumber")
            }
            row["cik"] = p.stem.split(".")[0]
            all_filings.append(row)
            accession_lookup[str(row["accessionNumber"])] = row
    filings = pd.DataFrame(all_filings)
    sec = {"submissions_companies": len(submissions), "indexed_filings": len(filings)}
    form_counts = filings.form.value_counts()
    sec["form_counts"] = {str(k): int(v) for k, v in form_counts.items()}
    for name, mask in {
        "form4": filings.form.eq("4"),
        "form4_amendment": filings.form.eq("4/A"),
        "earnings_8k_item202": filings.form.eq("8-K")
        & filings["items"].fillna("").str.contains(r"(?:^|,)2\.02(?:,|$)", regex=True),
        "tenk": filings.form.eq("10-K"),
    }.items():
        rows = filings[mask]
        sec[name] = {
            "metadata_rows": len(rows),
            "issuers": int(rows.cik.nunique()),
            "filing_range": range_of(rows.filingDate),
            "acceptance_range": range_of(rows.acceptanceDateTime),
            "missing_acceptance": int(
                rows.acceptanceDateTime.isna().sum() + rows.acceptanceDateTime.eq("").sum()
            ),
        }
    text_files = list((DATA / "sec/text").glob("*/*.txt.gz"))
    text_records = [accession_lookup.get(p.name.removesuffix(".txt.gz"), {}) for p in text_files]
    sec["cleaned_text_cache"] = {
        "files": len(text_files),
        "companies": len({p.parent.name for p in text_files}),
        "forms": dict(Counter(r.get("form", "unmatched") for r in text_records)),
        "filing_range": range_of([r.get("filingDate") for r in text_records]),
        "original_html_xml_preserved": False,
    }
    tenk_files = list((DATA / "sec/tenk").glob("*/*.json.gz"))
    tenk_records = [accession_lookup.get(p.name.removesuffix(".json.gz"), {}) for p in tenk_files]
    sec["tenk_word_vectors"] = {
        "files": len(tenk_files),
        "companies": len({p.parent.name for p in tenk_files}),
        "filing_range": range_of([r.get("filingDate") for r in tenk_records]),
        "original_filing_documents": False,
    }
    sec["form4_transaction_xml_cached"] = False
    sec["historical_earnings_announcement_schedule_cached"] = False
    out["sec"] = sec
    out["llm_scores"] = {}
    for directory in sorted((DATA / "llm/fundamental_scores").glob("*")):
        if not directory.is_dir():
            continue
        scores = directory / "scores.parquet"
        out["llm_scores"][directory.name] = (
            parquet_summary(str(scores.relative_to(DATA))) if scores.exists() else {"rows": 0}
        )
    live = DATA / "live"
    out["forward_evidence"] = {
        "fill_csv_files": len(list(live.rglob("fills.csv"))),
        "orb_directory_exists": (live / "orb").exists(),
        "shadow_equity_rows": len(pd.read_csv(live / "daily_book_shadow/equity.csv")),
        "scanner_files": [],
    }
    for p in sorted((live / "scanner").glob("*.json")):
        scans = json.loads(p.read_text(encoding="utf-8"))
        out["forward_evidence"]["scanner_files"].append(
            {
                "date": p.stem,
                "snapshots": len(scans),
                "nonempty_snapshots": sum(bool(v.get("symbols")) for v in scans.values()),
                "symbol_counts": {
                    k.split(" ERROR")[0]: len(v.get("symbols", [])) for k, v in scans.items()
                },
            }
        )
    out["other_datasets"] = {
        "congress": parquet_summary("congress/trades.parquet"),
        "social_posts": parquet_summary("social/serenity/posts.parquet", ("ts",)),
        "social_mentions": parquet_summary("social/serenity/mentions.parquet", ("ts",)),
    }
    out["absent_capabilities"] = {
        "futures_contract_history_rolls_point_values_margin": True,
        "options_chains_greeks_bid_ask_and_corporate_actions": True,
        "crypto_exchange_spot_perpetual_bars_and_funding": True,
        "historical_equity_nbbo_quotes": True,
        "security_master_with_permanent_ids_for_ticker_reuse": True,
        "historical_short_borrow_availability_and_fees": True,
        "local_short_interest_dataset": True,
    }
    out["absence_scope"] = (
        "No dedicated source module or dataset found in repository/data inventory. "
        "ETF exposures and downloaded research HTML are not underlying contract histories."
    )
    supplemental(out)
    write_outputs(out)
    print(json.dumps({k: v for k, v in out.items() if k != "daily_adjusted_bars"}, indent=2))


if __name__ == "__main__":
    main()
