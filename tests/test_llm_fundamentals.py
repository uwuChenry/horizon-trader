import json
import subprocess

import numpy as np
import pandas as pd
import pytest

from horizon_trader.datasources import sec
from horizon_trader.llm import fundamentals as LF


def _e(val, start, end, filed, form="10-Q", accn="a"):
    e = {"val": val, "end": end, "filed": filed, "form": form, "accn": accn}
    if start:
        e["start"] = start
    return e


def _facts(tags):
    return {"facts": {"us-gaap": {t: {"units": {"USD": es}} for t, es in tags.items()}}}


REVENUE = [
    _e(10, "2023-01-01", "2023-03-31", "2023-05-01"),
    _e(11, "2023-04-01", "2023-06-30", "2023-08-01"),
    _e(12, "2023-07-01", "2023-09-30", "2023-11-01"),
    _e(50, "2023-01-01", "2023-12-31", "2024-02-20", form="10-K"),  # Q4 = 50 - 33 = 17
    _e(20, "2024-01-01", "2024-03-31", "2024-05-01"),
    _e(99, "2024-01-01", "2024-03-31", "2025-05-01"),  # restated a year later: ignored
    _e(30, "2024-04-01", "2024-06-30", "2024-08-01"),
]


def test_quarterly_table_derives_q4_and_keeps_first_reported_values():
    q = sec.quarterly_table(_facts({"Revenues": REVENUE}), asof="2024-12-31")
    assert q["revenue"].tolist() == [10, 11, 12, 17, 20, 30]
    assert q.loc["2023-12-31", "filed"] == pd.Timestamp("2024-02-20")
    assert q.loc["2024-03-31", "revenue_yoy"] == pytest.approx(1.0)  # 20 vs 10 a year earlier


def test_quarterly_table_only_sees_filings_before_asof():
    q = sec.quarterly_table(_facts({"Revenues": REVENUE}), asof="2024-02-20")
    assert q["revenue"].tolist() == [10, 11, 12]  # the 10-K filed that day isn't known yet


def test_latest_balance_uses_latest_period_first_reported():
    facts = _facts(
        {
            "Assets": [
                _e(100, None, "2024-03-31", "2024-05-01"),
                _e(105, None, "2024-03-31", "2024-08-01"),  # comparative re-report
                _e(120, None, "2024-06-30", "2024-08-01"),
            ]
        }
    )
    assert sec.latest_balance(facts, "2024-07-01") == {"assets": 100, "as_of": "2024-03-31"}
    assert sec.latest_balance(facts, "2024-09-01") == {"assets": 120, "as_of": "2024-06-30"}


def test_mdna_excerpt_skips_the_table_of_contents():
    text = (
        "Item 2. Management’s Discussion and Analysis ... 25\nItem 3. Quantitative and "
        "Qualitative Disclosures ... 40\n" + "filler " * 50 + "\nManagement's Discussion and "
        "Analysis\nRevenue grew strongly. " + "detail " * 200 + "\nItem 3. Quantitative and "
        "Qualitative Disclosures about market risk"
    )
    excerpt, found = sec.mdna_excerpt(text)
    assert found and "Revenue grew strongly" in excerpt
    assert "Quantitative" not in excerpt
    assert sec.mdna_excerpt("no heading here", 5) == ("no he", False)


def test_earnings_release_picks_latest_202_8k_before_asof(monkeypatch):
    subs = {
        "filings": {
            "recent": {
                "accessionNumber": ["1", "2", "3"],
                "form": ["8-K", "8-K", "8-K"],
                "filingDate": ["2026-07-01", "2026-08-20", "2026-09-30"],
                "items": ["2.02,9.01", "5.02", "2.02,9.01"],
            }
        }
    }
    index = {"directory": {"item": [{"name": "main.htm"}, {"name": "q4ex99-1.htm"}]}}
    monkeypatch.setattr(sec, "_cached_json", lambda *a, **k: index)
    monkeypatch.setattr(sec, "filing_text", lambda cik, accn, doc: f"text {accn} {doc}")
    got = sec.earnings_release(subs, "1", asof="2026-09-30")
    assert got["accn"] == "1" and got["doc"] == "q4ex99-1.htm"  # the 9-30 one isn't known yet
    assert sec.earnings_release(subs, "1", asof="2026-10-01")["accn"] == "3"


def _manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    out = LF.run_dir("2026-10-01")
    (out / "scores").mkdir(parents=True)
    manifest = {
        "asof": "2026-10-01",
        "universe_date": "2026-09-30",
        "prompt_sha": LF.prompt_sha(),
        "batches": {"batch_01": ["AAA", "BBB"]},
        "input_sha": {"AAA": "x", "BBB": "y"},
        "companies": {
            "AAA": {"cik": "1", "name": "A", "market_cap": 1e12},
            "BBB": {"cik": "2", "name": "B", "market_cap": 5e11},
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest))
    (out / "batches").mkdir()
    (out / "batches" / "batch_01.md").write_text(
        "# guide\n\n## AAA: A\n\n| quarter end | filed |\n\n## BBB: B\n\nNo quarterly XBRL results."
    )
    return out, manifest


def _score(t, s, sub=5, direction="stable"):
    return {
        "ticker": t,
        "score": s,
        **dict.fromkeys(LF.SUBSCORES, sub),
        "direction": direction,
        "reason": "r",
    }


def test_check_validates_and_logs_scores(tmp_path, monkeypatch):
    out, manifest = _manifest(tmp_path, monkeypatch)
    assert LF.check("2026-10-01", "m") is None  # nothing scored yet
    LF.write_scores(out, "batch_01", [_score("AAA", 11)], "subagent", "m")
    assert LF.validate(
        manifest, "batch_01", json.loads((out / "scores/m/batch_01.json").read_text())
    )
    LF.write_scores(out, "batch_01", [_score("AAA", 7), _score("BBB", 4)], "subagent", "m")
    df = LF.check("2026-10-01", "m")
    assert sorted(df["ticker"]) == ["AAA", "BBB"]
    assert (out / "scores_m.parquet").exists() and not (out / "scores.parquet").exists()
    assert set(df["model"]) == {"m"} and set(df["input_sha"]) == {"x", "y"}
    assert df.set_index("ticker")["has_filings"].to_dict() == {"AAA": True, "BBB": False}


def _today(monkeypatch, iso):
    class FakeDate(LF.date):
        @classmethod
        def today(cls):
            return LF.date.fromisoformat(iso)

    monkeypatch.setattr(LF, "date", FakeDate)


def test_run_calls_headless_claude_with_tools_off(tmp_path, monkeypatch):
    out, _ = _manifest(tmp_path, monkeypatch)
    _today(monkeypatch, "2026-10-01")
    (out / "batches" / "batch_01.md").write_text("prompt body")
    calls = []

    def fake_run(cmd, input, **kw):
        calls.append((cmd, input))
        payload = {"is_error": False, "structured_output": {"scores": [_score("AAA", 6)]}}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(LF.subprocess, "run", fake_run)
    LF.run("2026-10-01", model=LF.LEGACY_MODEL, workers=1)
    cmd, prompt = calls[0]
    assert cmd[:2] == ["claude", "-p"] and LF.LEGACY_MODEL in cmd
    assert cmd[cmd.index("--tools") + 1] == ""
    assert prompt == "prompt body"
    rec = json.loads((out / "scores" / "batch_01.json").read_text())  # legacy flat layout
    assert rec["backend"] == "claude -p" and rec["scores"][0]["ticker"] == "AAA"
    _today(monkeypatch, "2026-10-02")  # resuming a started month the next day is fine
    LF.run("2026-10-01", model=LF.LEGACY_MODEL, workers=1)
    assert len(calls) == 1  # finished batches are not re-scored


def test_run_scores_with_codex_into_its_own_folder(tmp_path, monkeypatch):
    out, _ = _manifest(tmp_path, monkeypatch)
    _today(monkeypatch, "2026-10-01")
    seen = []

    def fake_codex(prompt, model, web, schema):
        seen.append((model, web, schema is LF.SCHEMA))
        return {"structured_output": {"scores": [_score("AAA", 6), _score("BBB", 3)]},
                "reasoning_effort": "high", "usage": {"input_tokens": 10}}  # fmt: skip

    monkeypatch.setattr(LF, "codex", fake_codex)
    LF.run("2026-10-01", model="gpt-6.1-sol", workers=1)
    assert seen == [("gpt-6.1-sol", False, True)]  # no tools, the scores schema
    rec = json.loads((out / "scores" / "gpt-6.1-sol" / "batch_01.json").read_text())
    assert rec["backend"] == "codex exec" and rec["usage"] == {"input_tokens": 10}
    assert not (out / "scores" / "batch_01.json").exists()
    df = LF.check("2026-10-01", "gpt-6.1-sol")
    assert set(df["model"]) == {"gpt-6.1-sol"} and (out / "scores_gpt-6.1-sol.parquet").exists()


def test_a_new_model_cannot_start_a_past_month(tmp_path, monkeypatch):
    _manifest(tmp_path, monkeypatch)
    _today(monkeypatch, "2026-11-05")
    monkeypatch.setattr(LF, "codex", lambda *a, **k: pytest.fail("must not be called"))
    with pytest.raises(SystemExit, match="no back-fill"):
        LF.run("2026-10-01", model="gpt-6.1-sol", workers=1)


def test_load_runs_keeps_models_apart(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    for asof, name, model in [
        ("2026-10-01", "scores.parquet", LF.LEGACY_MODEL),
        ("2026-11-05", "scores.parquet", LF.LEGACY_MODEL),
        ("2026-11-05", "scores_gpt-6.1-sol.parquet", "gpt-6.1-sol"),
    ]:
        out = LF.run_dir(asof)
        out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([_score("AAA", 5)]).assign(model=model).to_parquet(out / name)
    runs = LF.load_runs()
    assert sorted(runs[LF.LEGACY_MODEL]) == ["2026-10-01", "2026-11-05"]
    assert sorted(runs["gpt-6.1-sol"]) == ["2026-11-05"]


def test_parse_claude_output_falls_back_to_result_text():
    wrapped = {"is_error": False, "result": json.dumps({"scores": [{"ticker": "X"}]})}
    assert LF.parse_claude_output(json.dumps(wrapped)) == [{"ticker": "X"}]
    with pytest.raises(RuntimeError):
        LF.parse_claude_output(json.dumps({"is_error": True, "result": "boom"}))


def test_evaluate_runs_measures_ic_from_the_day_after_asof():
    idx = pd.bdate_range("2026-09-28", periods=80)
    growth = {"AAA": 0.01, "BBB": 0.0, "CCC": -0.01}
    closes = pd.DataFrame({t: 100 * (1 + g) ** np.arange(80) for t, g in growth.items()}, idx)
    scores = pd.DataFrame([_score("AAA", 9), _score("BBB", 5), _score("CCC", 2)]).assign(model="m")
    table = LF.evaluate_runs({"2026-10-01": scores}, closes)
    assert table.loc["2026-10-01", "IC 1m"] == pytest.approx(1.0)
    expected = 1.01**21 - 1
    assert table.loc["2026-10-01", "top20 1m"] == pytest.approx((expected + 0 + 0.99**21 - 1) / 3)
    assert LF.forward_returns(closes, "2026-12-31", 21) is None  # future not known yet


def test_evaluate_skips_companies_without_filings():
    idx = pd.bdate_range("2026-09-28", periods=40)
    closes = pd.DataFrame({"AAA": np.linspace(100, 120, 40), "BBB": np.linspace(100, 80, 40)}, idx)
    scores = pd.DataFrame([_score("AAA", 9), _score("BBB", 2)]).assign(
        model="m", has_filings=[True, False]
    )
    table = LF.evaluate_runs({"2026-10-01": scores}, closes)
    assert table.loc["2026-10-01", "n"] == 1
