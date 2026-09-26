from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from horizon_trader import config  # noqa: E402
from horizon_trader.dashboard import notes as N  # noqa: E402

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


def test_research_page_renders_notes_and_papers(notes):
    at = AppTest.from_file(str(DASH / "research.py"), default_timeout=30).run()
    assert not at.exception, at.exception
    assert set(at.sidebar.radio[0].options) == {"Strategy survey", "b llm"}
    at.sidebar.radio[0].set_value(notes / "a_survey.md").run()
    assert "PEAD is dead" in " ".join(m.value for m in at.markdown)
    assert len(at.tabs) == 2 and len(at.dataframe[0].value) == 3


def test_research_search_filters_notes_and_papers(notes):
    at = AppTest.from_file(str(DASH / "research.py"), default_timeout=30).run()
    at.sidebar.text_input[0].input("lopez").run()
    assert at.sidebar.radio[0].options == ["b llm"]
    assert len(at.dataframe[0].value) == 1
    at.sidebar.text_input[0].input("nothing matches").run()
    assert not at.exception and "No research notes mention" in at.info[0].value


def test_navigation_entry_point_runs(notes, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(notes.parent))  # no saved runs: Backtests shows a hint
    at = AppTest.from_file(str(DASH / "nav.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    at.switch_page(str(DASH / "research.py")).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Research"
