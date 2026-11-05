"""Audit generated IFVG artifacts and replay causal signals on real data.

Run after the study and the recorded pytest command:
    python research/ifvg/verify.py
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.config import REPO_ROOT, data_dir
from horizon_trader.execution.costs import IBKR_PLANS
from horizon_trader.intraday import ifvg as S
from horizon_trader.intraday.ifvg_study import STUDY, digest
from horizon_trader.results.catalog import load_manifest


def main():
    out = Path(__file__).resolve().parent
    artifact = data_dir() / STUDY
    paths = pd.read_parquet(artifact / "trade_paths.parquet")
    fills = pd.read_parquet(artifact / "fills.parquet")
    daily = pd.read_parquet(artifact / "daily.parquet")
    manifest = json.loads((out / "manifest.json").read_text())
    table = pd.read_csv(out / "metrics.csv")
    checks = []

    assert len(table) == 216
    assert not paths.duplicated(["date", "ticker", "strategy", "target_r"]).any()
    assert (paths.entry_time == paths.signal_time).all()
    assert (paths.entry_time <= paths.exit_time).all()
    assert (paths.inversion_time <= paths.signal_time).all()
    retests = paths[paths.strategy.str.endswith("retest")]
    assert (retests.inversion_time < retests.signal_time).all()
    assert ((retests.signal_time - retests.inversion_time) <= pd.Timedelta(minutes=30)).all()
    gaps = paths[paths.strategy.str.startswith("ifvg")]
    assert (gaps.formed_time < gaps.inversion_time).all()
    assert ((gaps.inversion_time - gaps.formed_time) <= pd.Timedelta(minutes=60)).all()
    assert (paths.entry_time.dt.hour * 60 + paths.entry_time.dt.minute <= 690).all()
    np.testing.assert_allclose(
        paths.gross_R, paths.side * (paths.exit_px - paths.entry_px) / paths.stop_dist
    )
    assert (
        paths.side * (paths.target - paths.entry_px) >= paths.target_r * paths.stop_dist - 1e-8
    ).all()
    assert (
        paths.side * (paths.target - paths.entry_px) < paths.target_r * paths.stop_dist + 0.0100001
    ).all()
    checks.append(
        "All trade paths: chronology, one trade/day, expiry, retest timing and target geometry"
    )

    assert (fills.qty == fills.qty.astype(int)).all()
    assert (fills.planned_loss <= fills.equity_before * 0.01 + 1e-8).all()
    assert (fills.qty * fills.entry_fill <= fills.equity_before + 1e-8).all()
    np.testing.assert_allclose(fills.pnl, fills.gross_pnl - fills.fees - fills.slippage)
    np.testing.assert_allclose(fills.equity_after, fills.equity_before + fills.pnl)
    for f in fills[fills.cost_case == "net"].sample(100, random_state=18).itertuples():
        expected = IBKR_PLANS["tiered"].total(f.side * f.qty, f.entry_fill)
        expected += IBKR_PLANS["tiered"].total(-f.side * f.qty, f.exit_fill)
        assert abs(f.fees - expected) < 1e-9
    checks.append(
        "All sized fills: whole shares, risk/capital caps, gross/net reconciliation; "
        "100 fee rechecks"
    )

    keys = ["ticker", "strategy", "target_r", "period", "cost_case"]
    for _, d in daily.groupby(keys):
        d = d.sort_values("date")
        np.testing.assert_allclose(d.equity, 5000 + d.pnl.cumsum())
        np.testing.assert_allclose(d.equity, 5000 * (1 + d["return"]).cumprod())
    totals = daily.groupby(keys).pnl.sum().sort_index()
    fill_totals = fills.groupby(keys).pnl.sum().reindex(totals.index, fill_value=0)
    np.testing.assert_allclose(totals, fill_totals, atol=1e-8)
    checks.append("All 216 independent accounts reconcile daily equity, returns and trade P&L")

    for record in manifest["inputs"]:
        assert digest(Path(record["path"])) == record["sha256"]
    assert digest(out / "protocol.md") == manifest["protocol_sha256"]
    for name, sha in manifest["source_hashes"].items():
        path = (
            REPO_ROOT / "uv.lock"
            if name == "uv.lock"
            else REPO_ROOT / "src/horizon_trader/execution/costs.py"
            if name == "costs.py"
            else REPO_ROOT / "src/horizon_trader/intraday" / name
        )
        assert digest(path) == sha
    for name, sha in manifest["output_hashes"].items():
        assert digest(out / name if name == "metrics.csv" else artifact / name) == sha
    checks.append("Input, source, protocol and principal output hashes match the run manifest")

    sample = paths[paths.target_r == 2].sample(64, random_state=20261018)
    for ticker, subset in sample.groupby("ticker"):
        minutes = pd.read_parquet(data_dir() / "massive/derived" / f"minute_{ticker}.parquet")
        for t in subset.itertuples():
            b = minutes[minutes.date == t.date].copy()
            prefix = b[b.ts < t.signal_time]
            decisions = S.signals(S.candles(prefix), t.strategy)
            assert any(
                s["signal_time"] == t.signal_time
                and s["side"] == t.side
                and s["lower"] == t.lower
                and s["upper"] == t.upper
                for s in decisions
            )
            entry = b[b.ts == t.entry_time].iloc[0]
            assert entry.open == t.entry_px
            # Independent vectorized barrier walk. At the first relevant minute,
            # opening prices resolve known ordering before high/low ambiguity.
            segment = b[(b.ts >= t.entry_time) & (b.ts <= t.exit_time)]
            stop_hit = segment.low <= t.stop if t.side == 1 else segment.high >= t.stop
            target_hit = segment.high >= t.target if t.side == 1 else segment.low <= t.target
            events = segment[stop_hit | target_hit]
            if t.exit_reason == "session_end":
                assert events.empty or events.ts.iloc[0] == t.exit_time
                assert t.exit_px == segment.open.iloc[-1]
            else:
                assert events.ts.iloc[0] == t.exit_time
                bar = events.iloc[0]
                if t.side * (bar.open - t.stop) <= 0:
                    expected = bar.open
                elif t.side * (bar.open - t.target) >= 0:
                    expected = t.target
                elif bar.low <= t.stop if t.side == 1 else bar.high >= t.stop:
                    expected = t.stop
                else:
                    expected = t.target
                assert abs(t.exit_px - expected) < 1e-8
    checks.append(
        "64 real trades: signals survive removing future minutes; independent barrier/fill replay"
    )

    result = load_manifest(out / "result.json", data_dir())
    assert all(a.path.exists() for a in result.artifacts)
    checks.append("Results catalog loads the descriptor and every registered artifact exists")
    suite = ET.parse(out / "verification.xml").getroot()
    cases = suite.findall(".//testcase")
    assert len(cases) >= 20 and not suite.findall(".//failure") and not suite.findall(".//error")
    verification = dict(
        verified_at=datetime.now(UTC).isoformat(),
        checks=checks,
        passed=True,
        pytest_cases=len(cases),
        pytest_xml_sha256=digest(out / "verification.xml"),
        tests_source_sha256=digest(REPO_ROOT / "tests/test_ifvg.py"),
        audit_source_sha256=digest(Path(__file__)),
        trade_paths=len(paths),
        sized_fills=len(fills),
        independent_accounts=len(table),
    )
    (out / "verification.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
