import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from horizon_trader import config
from horizon_trader.backtest import bundle
from horizon_trader.results import catalog as C
from horizon_trader.results import check


@pytest.fixture
def roots(tmp_path, monkeypatch):
    repo, data = tmp_path / "repo", tmp_path / "data"
    repo.mkdir()
    data.mkdir()
    monkeypatch.setattr(config, "REPO_ROOT", repo)
    monkeypatch.setenv("HT_DATA_DIR", str(data))
    return repo, data


def study(repo, **extra):
    directory = repo / "research" / "new_study"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.md").write_text("# Study\nEvidence.", encoding="utf-8")
    pd.DataFrame({"date": ["2026-10-01", "2026-10-02"], "a": [100, 103]}).to_csv(
        directory / "equity.csv", index=False
    )
    C.write_manifest(
        directory / "result.json",
        id="research:new",
        name="New study",
        kind="research",
        include=["*.md", "*.csv"],
        **extra,
    )
    return directory


def test_old_and_new_bundles_and_research_share_catalog_without_rewriting(roots):
    repo, data = roots
    old = data / "results" / "old"
    old.mkdir(parents=True)
    raw = '{"name":"Old","strategy":"baseline","start":"2020-01-01","end":"2020-01-03"}'
    (old / "meta.json").write_text(raw, encoding="utf-8")
    equity = pd.Series([100.0, 102], index=pd.date_range("2026-01-01", periods=2))
    new = bundle.save_run("new bundle", equity, pd.DataFrame(columns=bundle.TRADE_COLUMNS))
    study(repo)
    records, issues = C.discover()
    assert not issues and len(records) == 3
    assert {r.id for r in records} == {"backtest:old", f"backtest:{new.name}", "research:new"}
    assert (old / "meta.json").read_text(encoding="utf-8") == raw
    assert not (old / "result.json").exists()
    assert len(bundle.list_runs()) == 2


def test_missing_artifacts_and_invalid_manifest_do_not_hide_other_results(roots):
    repo, data = roots
    study(repo, artifacts=[{"path": "missing.csv", "role": "metrics"}])
    broken = data / "results" / "broken"
    broken.mkdir(parents=True)
    (broken / "result.json").write_text("[]", encoding="utf-8")
    (broken / "meta.json").write_text('{"name":"recoverable old run"}', encoding="utf-8")
    records, issues = C.discover()
    assert len(records) == 2 and len(issues) == 1
    result = next(r for r in records if r.kind == "research")
    assert any(not a.path.exists() for a in result.artifacts)


def test_portable_data_references_and_catalog_refresh(roots):
    repo, data = roots
    (data / "experiment").mkdir()
    artifact = data / "experiment" / "metrics.csv"
    artifact.write_text("a\n1\n", encoding="utf-8")
    study(repo, artifacts=[{"path": "data:experiment/metrics.csv"}])
    records, _ = C.discover()
    assert artifact in [a.path for a in records[0].artifacts]
    extra = repo / "research" / "new_study" / "more.csv"
    extra.write_text("a\n2\n", encoding="utf-8")
    records, _ = C.discover()
    assert extra in [a.path for a in records[0].artifacts]


@pytest.mark.parametrize("ref", ["../secret.json", "data:../secret.json", "credentials.env"])
def test_manifest_references_cannot_escape_roots(roots, ref):
    repo, data = roots
    path = study(repo, artifacts=[{"path": ref}]) / "result.json"
    with pytest.raises(ValueError):
        C.load_manifest(path, data)


def test_forward_ledger_refreshes_and_preserves_order_fills(roots):
    _, data = roots
    ledger = data / "live" / "daily_book_shadow"
    ledger.mkdir(parents=True)
    equity = ledger / "equity.csv"
    equity.write_text("date,equity,cash\n2026-10-01,5000,100\n", encoding="utf-8")
    records, issues = C.discover()
    assert not issues and records[0].kind == "shadow" and records[0].end == "2026-10-01"
    equity.write_text(
        "date,equity,cash\n2026-10-01,5000,100\n2026-10-02,5001,101\n", encoding="utf-8"
    )
    records, _ = C.discover()
    assert records[0].end == "2026-10-02"
    curves = C.equity_curves(C.read_table(equity))
    assert list(curves) == ["equity"] and curves.iloc[-1, 0] == 5001


def test_equity_adapters_preserve_all_configurations_and_reject_duplicate_paths():
    long = pd.DataFrame(
        {
            "date": ["2026-01-01"] * 2 + ["2026-01-02"] * 2,
            "equity": [100, 200, 110, 190],
            "capital": [100, 200, 100, 200],
            "strategy": ["a"] * 4,
        }
    )
    curves = C.equity_curves(long)
    assert curves.shape == (2, 2)
    assert curves.iloc[-1].tolist() == [110, 190]
    pd.testing.assert_frame_equal(C.equity_curves(curves), curves)
    with pytest.raises(ValueError):
        C.equity_curves(pd.concat([long, long.iloc[:1]]))


@pytest.mark.parametrize("exit_code,failures", [(0, 0), (1, 1)])
def test_check_runner_publishes_actual_test_status(roots, monkeypatch, exit_code, failures):
    repo, _ = roots
    monkeypatch.setattr(check.sys, "argv", ["check", "tests/test_one.py"])

    def run(command, **kwargs):
        assert kwargs["cwd"] == repo
        xml = Path(next(a.split("=", 1)[1] for a in command if a.startswith("--junitxml=")))
        xml.write_text(
            f'<testsuites><testsuite tests="2" failures="{failures}" '
            'errors="0" skipped="0"/></testsuites>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, exit_code, stdout="actual test output")

    monkeypatch.setattr(check.subprocess, "run", run)
    assert check.main() == exit_code
    records, issues = C.discover()
    assert not issues and len(records) == 1
    info = records[0].metadata
    assert info["status"] == ("passed" if not failures else "failed")
    assert info["counts"]["passed"] == 2 - failures
    assert info["code_sha256"] == C.code_fingerprint()
    assert "tests/test_one.py" in info["command"]


def test_code_fingerprint_detects_uncommitted_edits(roots):
    repo, _ = roots
    (repo / "src").mkdir()
    path = repo / "src" / "a.py"
    path.write_text("x = 1", encoding="utf-8")
    old = C.code_fingerprint()
    path.write_text("x = 2", encoding="utf-8")
    assert C.code_fingerprint() != old


def test_schema_and_duplicate_id_errors_are_visible(roots):
    repo, _ = roots
    directory = study(repo)
    duplicate = directory / "duplicate"
    duplicate.mkdir()
    (duplicate / "result.json").write_bytes((directory / "result.json").read_bytes())
    records, issues = C.discover()
    assert len(records) == 1 and "Duplicate result id" in issues[0]
    info = json.loads((duplicate / "result.json").read_text(encoding="utf-8"))
    info["schema_version"] = 99
    (duplicate / "result.json").write_text(json.dumps(info), encoding="utf-8")
    _, issues = C.discover()
    assert "schema_version" in issues[0]


def test_test_fixtures_are_not_discovered_as_real_results(roots):
    _, data = roots
    run = data / "checks" / "actual_check"
    C.write_manifest(run / "result.json", id="tests:actual", name="Actual", kind="tests")
    C.write_manifest(
        run / "tmp" / "fixture" / "result.json", id="fake", name="Fake", kind="research"
    )
    records, issues = C.discover()
    assert not issues and [r.id for r in records] == ["tests:actual"]
