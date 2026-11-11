"""The research folder format: one folder per study with a valid, curated result.json."""

import json

import pytest

from horizon_trader import config
from horizon_trader.results import index
from horizon_trader.results.catalog import load_manifest, write_manifest


def test_every_study_in_the_repo_follows_the_format_and_the_index_is_current():
    found, problems = index.studies()
    assert problems == []
    assert len(found) > 20
    text = index.render(found, config.REPO_ROOT / "research")
    readme = (config.REPO_ROOT / "research" / "README.md").read_text(encoding="utf-8")
    assert readme == text, "run: uv run python -m horizon_trader.results.index"


def test_rerunning_a_study_keeps_its_curated_fields(tmp_path):
    path = tmp_path / "study" / "result.json"
    write_manifest(path, id="research:study", name="Study", kind="research", start="2020-01-01")
    curated = json.loads(path.read_text(encoding="utf-8"))
    curated.update(status="dead", verdict="Loses after costs.", tags=["orb"])
    path.write_text(json.dumps(curated), encoding="utf-8")

    # the experiment script runs again with fresh numbers and its own (older) id
    write_manifest(path, id="research:study-v0", name="x", kind="research", start="2021-01-01")
    info = json.loads(path.read_text(encoding="utf-8"))
    assert info["id"] == "research:study"
    assert (info["status"], info["tags"]) == ("dead", ["orb"])
    assert info["verdict"] == "Loses after costs."
    assert info["start"] == "2021-01-01"


def test_manifest_rejects_unknown_status_and_finds_the_report(tmp_path):
    folder = tmp_path / "s"
    folder.mkdir()
    (folder / "report.md").write_text("# S\n", encoding="utf-8")
    path = folder / "result.json"
    base = {"schema_version": 1, "id": "research:s", "name": "S", "kind": "research"}
    path.write_text(json.dumps({**base, "status": "promising"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown status"):
        load_manifest(path, tmp_path)
    path.write_text(json.dumps({**base, "status": "dead"}), encoding="utf-8")
    result = load_manifest(path, tmp_path)
    assert result.report == folder / "report.md"  # README.md preferred, report.md fallback
    (folder / "README.md").write_text("# S\n", encoding="utf-8")
    assert result.report == folder / "README.md"


def test_index_flags_loose_notes_and_folders_without_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    research = tmp_path / "research"
    (research / "no_manifest").mkdir(parents=True)
    (research / "loose.md").write_text("# Loose\n", encoding="utf-8")
    good = research / "good"
    good.mkdir()
    (good / "README.md").write_text("# Good\n", encoding="utf-8")
    write_manifest(
        good / "result.json", id="research:good", name="Good", kind="research", status="core"
    )
    found, problems = index.studies()
    assert [r.id for r in found] == ["research:good"]
    assert any("no_manifest: no result.json" in p for p in problems)
    assert any("loose.md" in p for p in problems)
    assert any("good/result.json: missing verdict" in p for p in problems)
