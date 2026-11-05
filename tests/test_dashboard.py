"""The dashboard API: every page's endpoint on synthetic bundles, studies and ledgers."""

import json

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from horizon_trader import config  # noqa: E402
from horizon_trader.backtest import bundle  # noqa: E402
from horizon_trader.dashboard import bars, server  # noqa: E402
from horizon_trader.dashboard.routes import backtests  # noqa: E402
from horizon_trader.results.catalog import write_manifest  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    data, repo = tmp_path / "data", tmp_path / "repo"
    data.mkdir()
    monkeypatch.setenv("HT_DATA_DIR", str(data))
    monkeypatch.setattr(config, "REPO_ROOT", repo)
    backtests.load.cache_clear()
    backtests.headline.cache_clear()
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2023-01-02", periods=300)
    equity = pd.Series(10_000 * np.cumprod(1 + rng.normal(0.0005, 0.01, 300)), index=idx)
    t0 = pd.Timestamp("2023-01-03 09:40", tz="America/New_York")
    n = 120
    pnl = rng.normal(5, 40, n)
    trades = pd.DataFrame(
        {
            "entry_time": [t0 + pd.Timedelta(days=2 * i) for i in range(n)],
            "exit_time": [t0 + pd.Timedelta(days=2 * i, hours=3) for i in range(n)],
            "symbol": rng.choice(["AAA", "BBB", "CCC"], n),
            "side": rng.choice([1, -1], n),
            "qty": 100.0,
            "entry_px": 50.0,
            "exit_px": 50.0 + pnl / 100,
            "gross": pnl + 2,
            "costs": 2.0,
            "pnl": pnl,
            "R": pnl / 50,
            "exit_reason": rng.choice(["stop", "close"], n),
            "mae_R": rng.uniform(0, 1, n),
            "mfe_R": rng.uniform(0, 2, n),
            "relvol": rng.uniform(1, 40, n),
            "rank": 1,
        }
    )
    meta = {"strategy": "test", "oos_start": "2023-09-01", "caveats": ["synthetic data"]}
    holdings = pd.DataFrame(
        {
            "date": idx.repeat(2),
            "ticker": ["AAA", "BBB"] * len(idx),
            "shares": 10.0,
            "price": 50.0,
            "value": 500.0,
            "weight": 0.05,
        }
    )
    bundle.save_run(
        "synthetic A", equity, trades, meta, equity * 1.01, tables={"holdings": holdings}
    )
    bundle.save_run("synthetic B", equity * 1.1, trades.head(10), meta | {"strategy": "other"})

    study = repo / "research" / "demo"
    study.mkdir(parents=True)
    (study / "README.md").write_text(
        "# Demo study\n\nSee [the protocol](protocol.md) and https://arxiv.org/abs/1.\n",
        encoding="utf-8",
    )
    (study / "protocol.md").write_text("# Protocol\n", encoding="utf-8")
    pd.DataFrame({"date": idx[:5], "equity": [1.0, 1.1, 1.2, 1.1, 1.3]}).to_csv(
        study / "equity.csv", index=False
    )
    write_manifest(
        study / "result.json",
        id="research:demo",
        name="Demo study",
        kind="research",
        status="dead",
        verdict="Loses after costs.",
        tags=["orb"],
        include=["*.md", "*.csv"],
    )

    live = data / "live" / "book_shadow"
    live.mkdir(parents=True)
    pd.DataFrame({"date": idx[:4].strftime("%Y-%m-%d"), "equity": [5000, 5010, 4990, 5020],
                  "cash": 100.0}).to_csv(live / "equity.csv", index=False)  # fmt: skip
    (live / "state.json").write_text(
        json.dumps({"cash": 100.0, "holdings": {"SPY": 2.0}, "pending": []}), encoding="utf-8"
    )
    return TestClient(server.create_app(static=tmp_path / "no_dist"))


def test_backtest_list_detail_trades_and_compare(client):
    runs = client.get("/api/backtests").json()["runs"]
    assert [r["name"] for r in runs] == ["synthetic B", "synthetic A"]  # newest first
    rid = runs[1]["run_id"]
    assert runs[1]["holdings"] and np.isfinite(runs[1]["Sharpe"])

    d = client.get(f"/api/backtests/{rid}").json()
    assert d["meta"]["caveats"] == ["synthetic data"] and d["trades"] == 120
    assert len(d["equity"]) == 300 and len(d["benchmark"]) == 300
    assert d["monthly"]["months"][0] == "Jan" and d["split"]["columns"][0] == "index"
    times = [p["t"] for p in d["costs"]["net"]]
    assert times == sorted(set(times))  # charts need strictly rising times

    t = client.get(f"/api/backtests/{rid}/trades").json()
    assert t["trades"]["total"] == 120 and "relative volume" in t["dimensions"]
    assert sum(t["streaks"]["win"]) + sum(t["streaks"]["loss"]) > 0

    c = client.get(f"/api/backtests/compare?ids={runs[0]['run_id']},{rid}").json()
    assert [r["name"] for r in c["runs"]] == ["synthetic B", "synthetic A"]
    assert c["runs"][0]["growth"][0]["v"] == pytest.approx(1.0)

    h = client.get(f"/api/backtests/{rid}/holdings?date=2023-03-04").json()
    assert h["date"] == "2023-03-03"  # a Saturday snaps to the previous trading day
    assert h["positions"]["total"] == 2 and h["cash_weight"] == pytest.approx(0.9)
    assert client.get(f"/api/backtests/{runs[0]['run_id']}/holdings").status_code == 404
    assert client.get("/api/backtests/nope").status_code == 404


def test_studies_docs_files_and_papers(client):
    s = client.get("/api/studies").json()
    assert s["problems"] == [] and s["studies"][0]["status"] == "dead"
    d = client.get("/api/studies/demo").json()
    assert d["report"]["ref"] == "research/demo/README.md"
    assert [x["name"] for x in d["docs"]] == ["protocol.md"]
    assert [a["ref"] for a in d["artifacts"]] == ["research/demo/equity.csv"]
    doc = client.get("/api/doc?ref=research/demo/protocol.md").json()
    assert doc["study"] == "demo" and doc["title"] == "Protocol"
    eq = client.get("/api/files/equity?ref=research/demo/equity.csv").json()
    assert len(eq["series"][0]["points"]) == 5
    assert client.get("/api/files/table?ref=research/demo/equity.csv").json()["total"] == 5
    assert client.get("/api/papers").json()["rows"][0][1] == "https://arxiv.org/abs/1"


@pytest.mark.parametrize(
    "ref", ["research/../pyproject.toml", "research/demo/../../../x.csv", "data:../x.csv"]
)
def test_file_refs_cannot_escape_research_or_data(client, ref):
    assert client.get(f"/api/files/raw?ref={ref}").status_code in {400, 404}


def test_live_ledger_and_health(client):
    live = client.get("/api/live").json()
    (ledger,) = live["ledgers"]
    assert ledger["kind"] == "shadow" and ledger["return"] == pytest.approx(0.004)
    assert ledger["positions"][0]["symbol"] == "SPY" and ledger["positions"][0]["price"] is None
    names = [h["name"] for h in live["health"]]
    assert "book_shadow ledger" in names and "IB Gateway" in names
    assert live["kill_switch"] is False


def test_spa_fallback_serves_index_for_client_routes(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    c = TestClient(server.create_app(static=dist))
    assert c.get("/research/orb_ema").text == "<html>app</html>"
    assert c.get("/api/does-not-exist").status_code == 404


def test_trade_bars_for_daily_trade(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    idx = pd.bdate_range("2024-01-01", periods=200)
    px = pd.Series(np.linspace(100, 120, 200), index=idx)
    (tmp_path / "bars").mkdir()
    pd.DataFrame({"open": px, "high": px + 1, "low": px - 1, "close": px}).to_parquet(
        tmp_path / "bars" / "SPY.parquet"
    )
    trade = pd.Series({"symbol": "SPY", "entry_time": idx[100], "exit_time": idx[110]})
    got = bars.trade_bars(trade, "daily")
    assert got.index[0] >= idx[100] - pd.Timedelta(days=40) and len(got) < 200
