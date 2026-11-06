"""Forecast journal: pricing, risk rules, mirrors, marking, scoring and a full fake run."""

import json

import numpy as np
import pandas as pd
import pytest

from horizon_trader import config
from horizon_trader.agents import book, journal, prompts
from horizon_trader.agents.market import implied_move, nearest_expiry, packet


def _chain(spot: float, bid_ask: bool = True):
    strikes = np.arange(50.0, 151.0, 5.0)

    def side(right: str):
        intrinsic = np.maximum(strikes - spot, 0) if right == "P" else np.maximum(spot - strikes, 0)
        mid = intrinsic + 3.0 * np.exp(-(((strikes - spot) / (0.05 * spot)) ** 2)) + 0.2
        return pd.DataFrame({
            "contractSymbol": [f"X{right}{k:.0f}" for k in strikes], "strike": strikes,
            "bid": mid - 0.02 if bid_ask else 0.0, "ask": mid + 0.02 if bid_ask else 0.0,
            "lastPrice": mid, "impliedVolatility": 0.2,
        })  # fmt: skip

    return side("C"), side("P")


class FakeMarket:
    def __init__(self, spot=100.0, live=True):
        self.spot_px = {"SPY": spot, "QQQ": spot, "IWM": spot, "SMH": spot}
        self.live = live
        self.expiry_close = None
        idx = pd.bdate_range("2025-06-02", "2026-12-31")
        rng = np.random.default_rng(0)
        cols = ["SPY", "QQQ", "IWM", "SMH", "HYG", "IEF", "^VIX", "^VIX3M"]
        self.data = pd.DataFrame(
            100 * np.cumprod(1 + rng.normal(0, 0.01, (len(idx), len(cols))), axis=0),
            index=idx,
            columns=cols,
        )

    def closes(self, symbols, start):
        return self.data[[s for s in symbols if s in self.data]].loc[start:]

    def expiries(self, symbol):
        return ["2026-11-06", "2026-11-13", "2026-11-20", "2026-12-18"]

    def chain(self, symbol, expiry):
        return _chain(self.spot(symbol), self.live)

    def spot(self, symbol):
        return self.spot_px.get(symbol, 100.0)

    def raw_close(self, symbol, day):
        return self.expiry_close


def test_nearest_expiry_and_implied_move():
    m = FakeMarket()
    assert nearest_expiry(m.expiries("SPY"), "2026-11-05", 7) == "2026-11-13"
    assert nearest_expiry(m.expiries("SPY"), "2026-12-18", 7) is None
    mv = implied_move(m, "SPY", "2026-11-05")
    assert mv.source == "mid, yahoo" and 5 < mv.move_pct < 8  # straddle ~6.4 on a 100 stock
    assert implied_move(FakeMarket(live=False), "SPY", "2026-11-05").source == "last"


class LiveFake(FakeMarket):
    """IBKR has live quotes for some contracts only; the rest fall back to the chain's."""

    def __init__(self, live_for, **kw):
        super().__init__(**kw)
        self.live_for, self.asked = live_for, []

    def live_quotes(self, symbols):
        self.asked.append(list(symbols))
        return {s: (9.0, 9.5) for s in symbols if self.live_for(s)}


def test_requote_prefers_live_and_falls_back_per_contract():
    from horizon_trader.agents.market import requote

    m = LiveFake(lambda s: "C" in s[-9:])  # live quotes for calls only
    calls, puts = m.chain("SPY", "2026-11-13")
    rows = requote(m, pd.concat([calls.head(1), puts.head(1)]))
    assert list(rows["quote_source"]) == ["ibkr", "yahoo"]
    assert rows.iloc[0]["bid"] == 9.0 and rows.iloc[1]["bid"] == puts.iloc[0]["bid"]
    assert implied_move(m, "SPY", "2026-11-05").source == "mid, yahoo"  # one leg fell back
    m_all = LiveFake(lambda s: True)
    assert implied_move(m_all, "SPY", "2026-11-05").source == "mid, ibkr"


def test_priced_legs_record_their_quote_source():
    m = LiveFake(lambda s: True)
    pos, why = book.resolve(IDEA, m, "2026-11-05", book.Rules(), 2_000.0, "x", "idea")
    assert why == "ok" and pos["legs"][0]["quote_source"] == "ibkr" and pos["qty"] == 2
    assert pos["unit_entry"] == 9.5  # bought at the live ask
    assert book.mark(pos, m, book.Rules()) == 9.0 * 100 * pos["qty"]  # marked at the live bid


def test_packet_has_table_vol_credit_and_moves():
    md, nums = packet(FakeMarket(), "2026-11-05")
    assert "| SPY | S&P 500 |" in md and "VIX3M" in md and "HYG/IEF" in md
    assert nums["last_bar"] == "2026-11-05" and "SPY" in nums["tickers"]


IDEA = {"underlying": "SPY", "structure": "long_put", "days_to_expiry": 7, "otm_pct": 3,
        "spread_width_pct": 0, "horizon_days": 5, "confidence": 3, "thesis": "t",
        "invalidation": "i"}  # fmt: skip


def test_resolve_put_spread_and_shares():
    m, r = FakeMarket(), book.Rules()
    pos, why = book.resolve(IDEA, m, "2026-11-05", r, 150, "a", "idea")
    assert why == "ok" and pos["legs"][0]["strike"] == 95 and pos["expiry"] == "2026-11-13"
    assert pos["entry_cost"] <= 150 + r.fee_per_contract * pos["qty"]
    assert pos["exit_planned"] == "2026-11-12"  # 5 weekdays, before expiry
    spread = IDEA | {"structure": "put_debit_spread", "spread_width_pct": 5}
    pos, _ = book.resolve(spread, m, "2026-11-05", r, 150, "b", "idea")
    assert [leg["side"] for leg in pos["legs"]] == [1, -1]
    assert pos["legs"][1]["strike"] == 90  # 5% below the long 95 strike
    assert pos["unit_entry"] == pytest.approx(pos["legs"][0]["ask"] - pos["legs"][1]["bid"])
    sh, _ = book.resolve(IDEA | {"structure": "shares_long"}, m, "2026-11-05", r, 1e9, "c", "idea")
    assert sh["qty"] == 24  # $2,500 cap / ~$100


def test_resolve_rejects_closed_market_and_tiny_budget():
    r = book.Rules()
    pos, why = book.resolve(IDEA, FakeMarket(live=False), "2026-11-05", r, 150, "a", "idea")
    assert pos is None and "no live quote" in why
    atm = IDEA | {"otm_pct": -5}  # in the money: ~$5.5 a share = $550 a contract
    pos, why = book.resolve(atm, FakeMarket(), "2026-11-05", r, 150, "a", "idea")
    assert pos is None and "above the $150 budget" in why


def test_risk_caps_and_mirrors():
    m, r, positions = FakeMarket(), book.Rules(), []
    ideas = [IDEA, IDEA | {"structure": "call_debit_spread", "spread_width_pct": 3},
             IDEA | {"structure": "none"}, IDEA, IDEA]  # fmt: skip
    res = book.open_ideas_with_mirrors(ideas, m, "2026-11-05", r, positions)
    assert [x["status"] for x in res] == ["opened", "opened", "rejected", "rejected", "rejected"]
    assert "more than 3" in res[3]["reason"]
    kinds = [(p["kind"], p["structure"]) for p in positions]
    assert kinds == [("idea", "long_put"), ("mirror", "long_call"),
                     ("idea", "call_debit_spread"), ("mirror", "put_debit_spread")]  # fmt: skip
    assert book.premium_open(positions) <= r.premium_total  # mirrors don't count
    # The total premium cap binds before the per-idea cap.
    tight = book.Rules(premium_total=100)
    res = book.open_ideas_with_mirrors([IDEA], m, "2026-11-06", tight, positions)
    assert res[0]["status"] == "rejected"


def test_step_closes_at_horizon_trader_and_expiry():
    m, r, positions = FakeMarket(), book.Rules(), []
    shares = IDEA | {"structure": "shares_long", "horizon_days": 10}
    book.open_ideas_with_mirrors([IDEA, shares], m, "2026-11-05", r, positions)
    put, put_m, sh, sh_m = positions
    assert book.step(positions, m, "2026-11-06", r) and put["status"] == "open"
    m.spot_px["SPY"] = 90.0  # market falls 10%: the put gains, its call mirror loses
    book.step(positions, m, "2026-11-12", r)  # put horizon reached
    assert put["status"] == "closed" and put["exit_reason"] == "horizon" and put["pnl"] > 0
    assert put_m["status"] == "closed" and put_m["pnl"] < 0
    assert sh["status"] == "open"
    book.step(positions, m, "2026-11-13", r, close_ids={sh["id"]})
    assert sh["exit_reason"] == "trader" and sh["pnl"] < 0 and sh_m["pnl"] > 0  # short mirror

    # An option nobody marked before expiry settles from the unadjusted close.
    late = []
    book.open_ideas_with_mirrors([IDEA | {"horizon_days": 30}], m, "2026-11-05", r, late)
    m.live, m.expiry_close = False, 80.0
    book.step(late, m, "2026-11-16", r)
    assert late[0]["exit_reason"] == "expired"
    k = late[0]["legs"][0]["strike"]
    assert late[0]["exit_value"] == pytest.approx((k - 80) * 100 * late[0]["qty"])


def test_score_forecasts_and_summary():
    idx = pd.bdate_range("2026-01-01", periods=60)
    closes = pd.DataFrame({"SPY": np.linspace(100, 160, 60), "QQQ": np.linspace(100, 130, 60)},
                          index=idx)  # fmt: skip
    rows = []
    for d in idx[:40]:
        for t in ("SPY", "QQQ"):
            rows.append(
                {
                    "date": d.strftime("%Y-%m-%d"),
                    "ticker": t,
                    "horizon_days": 5,
                    "direction": "up",
                    "benchmark": "",
                    "confidence": 3,
                    "mandatory": True,
                }
            )
    rows.append(
        {
            "date": idx[0].strftime("%Y-%m-%d"),
            "ticker": "QQQ",
            "horizon_days": 5,
            "direction": "down",
            "benchmark": "SPY",
            "confidence": 4,
            "mandatory": False,
        }
    )
    rows.append(
        {
            "date": idx[-2].strftime("%Y-%m-%d"),
            "ticker": "SPY",
            "horizon_days": 20,
            "direction": "up",
            "benchmark": "",
            "confidence": 2,
            "mandatory": True,
        }
    )
    scored = book.score_forecasts(pd.DataFrame(rows), closes)
    assert scored["hit"].iloc[:80].eq(1).all()  # everything rose
    rel = scored.iloc[80]
    assert rel["hit"] == 1 and rel["edge"] > 0  # QQQ trailed SPY
    assert np.isnan(scored.iloc[81]["hit"])  # 20 days haven't passed
    s = book.summary(scored, [])
    five = next(f for f in s["forecasts"] if f["horizon"] == 5 and f["group"] == "all")
    assert five["n"] == 81 and five["always_up_hit_rate"] < 1  # the relative call
    assert five["n_nonoverlap"] == 8 + 8 + 1


def test_equity_curve_counts_ideas_not_mirrors():
    m, r, positions = FakeMarket(), book.Rules(), []
    book.open_ideas_with_mirrors([IDEA], m, "2026-11-05", r, positions)
    marks = pd.DataFrame(book.step(positions, m, "2026-11-06", r))
    eq = book.equity_curve(positions, marks, r)
    idea = positions[0]
    assert list(eq["date"]) == ["2026-11-05", "2026-11-06"]
    assert eq["equity"].iloc[0] == pytest.approx(r.account)
    assert eq["equity"].iloc[1] == pytest.approx(r.account + marks["value"].iloc[0]
                                                 - idea["entry_cost"])  # fmt: skip


def _fake_runner(calls):
    def runner(prompt, model, tools, schema):
        calls.append((prompt, model, tools, schema is not None))
        if schema is None:
            return {"result": f"report by {model} with tools {tools}"}
        return {"structured_output": {
            "regime": "risk_off", "bias": "short tech", "thesis": "x", "invalidation": "y",
            "debate_winner": "bear",
            "forecasts": [{"ticker": t, "horizon_days": h, "direction": "down", "benchmark": "",
                           "confidence": 3} for t, h in prompts.MANDATORY],
            "ideas": [IDEA | {"underlying": "QQQ"}], "close_ids": [],
        }}  # fmt: skip

    return runner


def test_full_run_writes_everything_and_never_rebuilds(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    calls = []
    rec = journal.run("2026-11-05", FakeMarket(), _fake_runner(calls))
    roles = [c for c in calls]
    assert len(roles) == 8  # 3 analysts, 2 cases, 2 rebuttals, trader
    web = [c for c in calls if c[2]]
    assert len(web) == 2 and all(c[1] == journal.MODELS["analyst"] for c in web)
    trader_prompt = calls[-1][0]
    assert "Bear rebuttal" in trader_prompt and "Earnings analyst" in trader_prompt
    assert rec["problems"] == [] and rec["resolution"][0]["status"] == "opened"

    root = config.data_dir() / "journal"
    day = root / "days" / "2026-11-05"
    assert {p.stem for p in (day / "reports").glob("*.md")} == {
        "market",
        "news",
        "earnings",
        "bull",
        "bear",
        "bull_rebuttal",
        "bear_rebuttal",
    }
    saved = json.loads((day / "decision.json").read_text(encoding="utf-8"))
    assert saved["prompt_sha"] == prompts.prompt_sha()
    assert len(pd.read_csv(root / "forecasts.csv")) == 6
    assert json.loads((root / "summary.json").read_text())["ideas"]["opened"] == 1
    live = config.data_dir() / "live" / journal.LEDGER
    assert (live / "equity.csv").exists() and "holdings" in json.loads(
        (live / "state.json").read_text()
    )
    with pytest.raises(SystemExit):
        journal.run("2026-11-05", FakeMarket(), _fake_runner([]))


def test_validate_flags_missing_mandatory():
    d = {"forecasts": [{"ticker": "SPY", "horizon_days": 5, "benchmark": ""}]}
    assert len(journal.validate(d)) == 5


def test_auto_runner_picks_the_backend_by_model(monkeypatch):
    got = []
    monkeypatch.setattr(journal, "codex", lambda p, m, web, schema: got.append(("codex", m, web))
                        or {"result": "x"})  # fmt: skip
    monkeypatch.setattr(journal, "claude", lambda p, m, t, s: got.append(("claude", m, t))
                        or {"result": "y"})  # fmt: skip
    journal.auto("p", "gpt-6.1-sol", journal.WEB, None)
    journal.auto("p", "gpt-6.1-sol", [], prompts.SCHEMA)
    journal.auto("p", "claude-opus-5-5", journal.WEB, None)
    assert got == [("codex", "gpt-6.1-sol", True), ("codex", "gpt-6.1-sol", False),
                   ("claude", "claude-opus-5-5", journal.WEB)]  # fmt: skip
    assert set(journal.MODELS.values()) == {"gpt-6.1-sol"}


def test_claude_cmd_tools():
    assert journal.claude_cmd("m", [], None)[-2:] == ["--tools", ""]
    cmd = journal.claude_cmd("m", journal.WEB, prompts.SCHEMA)
    assert "--allowedTools" in cmd and "WebSearch,WebFetch" in cmd and "--json-schema" in cmd


def test_dashboard_journal_api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from horizon_trader.dashboard import server

    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    c = TestClient(server.create_app(static=tmp_path / "no_dist"))
    assert c.get("/api/journal").json()["exists"] is False
    journal.run("2026-11-05", FakeMarket(), _fake_runner([]))
    j = c.get("/api/journal").json()
    assert j["days"][0]["regime"] == "risk_off" and j["days"][0]["opened"] == 1
    assert j["positions"]["total"] == 2 and j["forecasts"]["total"] == 6
    assert j["summary"]["ideas"]["opened"] == 1 and len(j["equity"]) == 1
    d = c.get("/api/journal/2026-11-05").json()
    assert set(d["reports"]) >= {"news", "bear_rebuttal"} and "Market packet" in d["packet"]
    assert d["meta"]["trader"]["model"] == journal.MODELS["trader"]
    assert c.get("/api/journal/../../etc").status_code == 404
