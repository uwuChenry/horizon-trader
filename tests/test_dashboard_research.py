from pathlib import Path

import pytest

from horizon_trader import config
from horizon_trader.dashboard import notes as N

DASH = Path(__file__).resolve().parents[1] / "src/horizon_trader/dashboard"

SURVEY = """# Strategy survey

PEAD is dead in large caps ([Martineau 2022](https://papers.ssrn.com/abs=3111607)).

## Sources
- Martineau (2022), Rest in Peace PEAD, CFR. https://papers.ssrn.com/abs=3111607
- Lou, Polk & Skouras, A Tug of War. https://personal.lse.ac.uk/tug.pdf.
"""
LLM = "no heading here, about LLM signals\n- Lopez-Lira & Tang. https://arxiv.org/abs/2304.07619\n"


@pytest.fixture
def notes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    research = tmp_path / "research"
    research.mkdir()
    (research / "a_survey.md").write_text(SURVEY, encoding="utf-8")
    (research / "b_llm.md").write_text(LLM, encoding="utf-8")
    return research


def test_links_markdown_and_bare_urls():
    got = N.links(SURVEY)
    assert got[0] == ("Martineau 2022", "https://papers.ssrn.com/abs=3111607")
    assert ("Lou, Polk & Skouras, A Tug of War", "https://personal.lse.ac.uk/tug.pdf") in got
    assert N.links("see https://x.org/a") == [("see", "https://x.org/a")]
    assert N.links("https://x.org/a") == [("https://x.org/a", "https://x.org/a")]
    two = "- Chen, Kelly & Xiu, Expected Returns. https://ssrn.com/1 (slides: https://w.edu/k.pdf)"
    assert N.links(two) == [
        ("Chen, Kelly & Xiu, Expected Returns", "https://ssrn.com/1"),
        ("Chen, Kelly & Xiu, Expected Returns (slides)", "https://w.edu/k.pdf"),
    ]


def test_papers_dedupes_urls_and_records_citing_notes(notes):
    p = N.papers(N.list_notes(notes)).set_index("url")
    assert len(p) == 3
    row = p.loc["https://papers.ssrn.com/abs=3111607"]
    assert row["title"] == "Martineau (2022), Rest in Peace PEAD, CFR"  # most descriptive label
    assert row["cited in"] == "Strategy survey" and row["source"] == "papers.ssrn.com"
    assert p.loc["https://arxiv.org/abs/2304.07619", "cited in"] == "b llm"


def test_local_links_do_not_offer_files_outside_research(notes):
    (notes.parent / "private.csv").write_text("secret", encoding="utf-8")
    path = notes / "escape.md"
    path.write_text("[private](../private.csv)", encoding="utf-8")
    assert N.local_links(path, notes) == []
