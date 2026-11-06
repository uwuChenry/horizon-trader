"""Daily option-chain snapshot from IBKR: our own options history, built forward.

    uv run python -m horizon_trader.datasources.ibkr_options_log capture [--only SPY QQQ]
    uv run python -m horizon_trader.datasources.ibkr_options_log check     # coverage per day

IBKR serves no history for expired options, so a chain not captured on a day is lost for good.
Run during market hours (scheduled weekdays 15:40 ET): single-stock options stop at 16:00.

For each underlying in config/options_log.yaml (plus any the forecast journal has open
positions in): the next few weekly and monthly expiries, strikes on a moneyness grid around the
price, and per contract bid/ask/sizes, last, volume, open interest and IBKR's model greeks/IV.
Written to data/ibkr/options/<date>/<UNDERLYING>.parquet with a manifest.json; an underlying
already captured that day is skipped (re-run to fill gaps). READ-ONLY: `readonly=True`
connection with its own client id; it never places an order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import time
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from horizon_trader import config

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
CLIENT_ID = 33  # journal quotes use 31; keep ids distinct so both can run
CHUNK = 80  # contracts per batch, under IBKR's ~100 simultaneous market-data lines
WAIT = 3.0  # seconds per batch for quotes and greeks to arrive
GENERIC_TICKS = "100,101"  # option volume, open interest


def settings() -> dict:
    path = config.REPO_ROOT / "config" / "options_log.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def out_dir(day: str) -> Path:
    return config.data_dir() / "ibkr" / "options" / day


def journal_underlyings() -> list[str]:
    """Underlyings of the forecast journal's open positions (so we log what it holds)."""
    path = config.data_dir() / "journal" / "book.json"
    if not path.exists():
        return []
    positions = json.loads(path.read_text(encoding="utf-8")).get("positions", [])
    return sorted({p["underlying"] for p in positions if p.get("status") == "open"})


# ---------- what to request (pure, tested) ----------


def is_monthly(d: date) -> bool:
    """Standard monthly expiry: the third Friday. (When that Friday is a holiday the monthly
    moves to Thursday and is missed here; the weeklies still cover the near term.)"""
    return 15 <= d.day <= 21 and d.weekday() == 4


def select_expiries(expirations: list[str], today: date, weeklies: int, monthlies: int) -> list:
    """The next `weeklies` expiries after today plus the next `monthlies` third Fridays."""
    future = sorted(e for e in set(expirations) if datetime.strptime(e, "%Y%m%d").date() > today)
    near = future[:weeklies]
    later = [e for e in future[weeklies:] if is_monthly(datetime.strptime(e, "%Y%m%d").date())]
    return near + later[:monthlies]


def select_strikes(strikes: list[float], spot: float, band: float, step: float, dense: float):
    """Every listed strike within +-dense of spot, plus the nearest strike to each step of
    moneyness out to +-band."""
    listed = sorted(k for k in set(strikes) if abs(k / spot - 1) <= band + step)
    if not listed:
        return []
    keep = {k for k in listed if abs(k / spot - 1) <= dense}
    n = int(round(band / step))
    for i in range(-n, n + 1):
        target = spot * (1 + i * step)
        keep.add(min(listed, key=lambda k: abs(k - target)))
    return sorted(keep)


# ---------- IBKR ----------


def _num(x) -> float | None:
    """A price/size/IV, or None for missing: IBKR uses NaN and -1 for "no data"."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or v < 0 else v


def spot_price(ib, stock) -> float | None:
    t = ib.reqMktData(stock, "", False, False)
    deadline = time.monotonic() + WAIT
    try:
        while time.monotonic() < deadline:
            ib.sleep(0.25)
            px = _num(t.marketPrice()) if hasattr(t, "marketPrice") else None
            if px:
                return px
        return _num(getattr(t, "last", None)) or _num(getattr(t, "close", None))
    finally:
        ib.cancelMktData(stock)


def chain_params(ib, stock) -> tuple[list[str], list[float]]:
    """Expirations and strikes of the SMART chain whose trading class is the symbol itself."""
    chains = ib.reqSecDefOptParams(stock.symbol, "", "STK", stock.conId)
    best = [c for c in chains if c.exchange == "SMART" and c.tradingClass == stock.symbol]
    best = best or [c for c in chains if c.exchange == "SMART"] or chains
    if not best:
        return [], []
    return sorted(best[0].expirations), sorted(best[0].strikes)


def snapshot_rows(ib, contracts: list, captured: str) -> list[dict]:
    """Stream a batch, wait for quotes and greeks, record whatever arrived, release the lines."""
    tickers = [ib.reqMktData(c, GENERIC_TICKS, False, False) for c in contracts]
    deadline = time.monotonic() + WAIT
    try:
        while time.monotonic() < deadline:
            ib.sleep(0.25)
            if all(_num(t.bid) is not None and getattr(t, "modelGreeks", None) for t in tickers):
                break
    finally:
        for c in contracts:
            ib.cancelMktData(c)
    rows = []
    for t in tickers:
        c, g = t.contract, getattr(t, "modelGreeks", None)
        oi = t.callOpenInterest if c.right == "C" else t.putOpenInterest
        rows.append({
            "captured_utc": captured, "underlying": c.symbol,
            "expiry": c.lastTradeDateOrContractMonth, "strike": float(c.strike),
            "right": c.right, "con_id": c.conId, "local_symbol": c.localSymbol,
            "bid": _num(t.bid), "ask": _num(t.ask), "bid_size": _num(t.bidSize),
            "ask_size": _num(t.askSize), "last": _num(t.last), "volume": _num(t.volume),
            "open_interest": _num(oi),
            "iv": _num(g.impliedVol) if g else None, "delta": g.delta if g else None,
            "gamma": g.gamma if g else None, "vega": g.vega if g else None,
            "theta": g.theta if g else None, "und_price": _num(g.undPrice) if g else None,
            "market_data_type": getattr(t, "marketDataType", None),
        })  # fmt: skip
    return rows


def capture_one(ib, symbol: str, today: date, cfg: dict) -> tuple[pd.DataFrame, dict]:
    from ib_async import Option, Stock

    stock = Stock(symbol, "SMART", "USD")
    if not ib.qualifyContracts(stock) or not stock.conId:
        return pd.DataFrame(), {"error": "could not qualify the underlying"}
    spot = spot_price(ib, stock)
    if not spot:
        return pd.DataFrame(), {"error": "no live underlying price (market closed or no data)"}
    expirations, strikes = chain_params(ib, stock)
    expiries = select_expiries(expirations, today, cfg["weeklies"], cfg["monthlies"])
    picked = select_strikes(strikes, spot, cfg["band"], cfg["grid_step"], cfg["dense_band"])
    candidates = [Option(symbol, e, k, r, "SMART", currency="USD", multiplier="100",
                         tradingClass=symbol)
                  for e in expiries for k in picked for r in ("C", "P")]  # fmt: skip
    # Not every strike lists for every expiry: qualification drops the ones that don't exist.
    contracts = []
    for i in range(0, len(candidates), 50):
        contracts += [c for c in ib.qualifyContracts(*candidates[i : i + 50]) if c and c.conId]
    captured = datetime.now(UTC).isoformat(timespec="seconds")
    rows = []
    for i in range(0, len(contracts), CHUNK):
        rows += snapshot_rows(ib, contracts[i : i + CHUNK], captured)
    df = pd.DataFrame(rows)
    if len(df):
        df["spot"] = spot
    quoted = int((df["bid"].notna() & df["ask"].notna()).sum()) if len(df) else 0
    meta = {"spot": spot, "expiries": expiries, "strikes": len(picked),
            "contracts": len(contracts), "quoted": quoted, "captured_utc": captured}  # fmt: skip
    return df, meta


def capture(day: date | None = None, only: list[str] | None = None, ib=None) -> dict:
    day = day or datetime.now(NY).date()
    cfg = settings()
    names = only or sorted(set(cfg["underlyings"]) | set(journal_underlyings()))
    out = out_dir(day.isoformat())
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("underlyings", {})
    manifest["config"] = cfg
    blob = json.dumps(cfg, sort_keys=True).encode()
    manifest["config_sha"] = hashlib.sha256(blob).hexdigest()[:12]
    own = ib is None
    if own:
        from horizon_trader.execution.ibkr import connect

        ib = connect(readonly=True, client_id=CLIENT_ID)
    try:
        ib.reqMarketDataType(1)  # live only: a delayed snapshot isn't worth storing
        for sym in names:
            path = out / f"{sym}.parquet"
            if path.exists():
                print(f"  {sym}: already captured")
                continue
            t0 = time.monotonic()
            try:
                df, meta = capture_one(ib, sym, day, cfg)
            except Exception as exc:  # noqa: BLE001 - one bad name shouldn't stop the rest
                df, meta = pd.DataFrame(), {"error": repr(exc)}
            meta["seconds"] = round(time.monotonic() - t0, 1)
            if len(df) and meta.get("quoted"):
                df.to_parquet(path, index=False)
            manifest["underlyings"][sym] = meta
            print(f"  {sym}: {meta.get('quoted', 0)}/{meta.get('contracts', 0)} quoted "
                  f"{meta.get('error', '')} ({meta['seconds']}s)", flush=True)  # fmt: skip
            manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    finally:
        if own:
            ib.disconnect()
    return manifest


def check(days: int = 20) -> pd.DataFrame:
    root = config.data_dir() / "ibkr" / "options"
    rows = []
    for d in sorted(root.glob("????-??-??"))[-days:]:
        path = d / "manifest.json"
        m = json.loads(path.read_text("utf-8")) if path.exists() else {}
        for sym, meta in m.get("underlyings", {}).items():
            rows.append({"date": d.name, "underlying": sym, "contracts": meta.get("contracts"),
                         "quoted": meta.get("quoted"), "error": meta.get("error", "")})  # fmt: skip
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("command", choices=["capture", "check"])
    p.add_argument("--only", nargs="*", help="capture just these underlyings")
    a = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if a.command == "check":
        df = check()
        print(df.to_string(index=False) if len(df) else "no snapshots yet")
        return
    from horizon_trader.config import require_ops

    require_ops("capture option chains")
    now = datetime.now(NY)
    if now.weekday() >= 5 or not (9 * 60 + 35 <= now.hour * 60 + now.minute <= 16 * 60):
        print("warning: outside 9:35-16:00 ET on a weekday; quotes will be missing or stale")
    m = capture(only=a.only)
    ok = sum(1 for v in m["underlyings"].values() if v.get("quoted"))
    print(f"{ok}/{len(m['underlyings'])} underlyings captured -> {out_dir(now.date().isoformat())}")


if __name__ == "__main__":
    main()
