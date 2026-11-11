from collections import Counter

import pandas as pd
import pytest

from horizon_trader.datasources import sec


def _e(val, end, accn, filed, form="10-K", start=None):
    e = {"val": val, "end": end, "accn": accn, "filed": filed, "form": form}
    if start:
        e["start"] = start
    return e


def _facts(tags: dict[str, list[dict]]) -> dict:
    return {"facts": {"us-gaap": {t: {"units": {"USD": es}} for t, es in tags.items()}}}


FY23 = ("2023-01-01", "2023-12-31")
FY22 = ("2022-01-01", "2022-12-31")


def test_tenk_table_takes_current_year_values_from_original_10ks():
    facts = _facts(
        {
            "Assets": [
                _e(90, "2022-12-31", "a23", "2024-02-20"),  # prior-year comparative
                _e(100, "2023-12-31", "a23", "2024-02-20"),
                _e(95, "2023-09-30", "q3", "2023-11-01", form="10-Q"),
                _e(111, "2023-12-31", "amend", "2024-05-01", form="10-K/A"),
            ],
            "StockholdersEquity": [_e(40, "2023-12-31", "a23", "2024-02-20")],
            "Revenues": [
                _e(50, FY22[1], "a23", "2024-02-20", start=FY22[0]),  # comparative year
                _e(60, FY23[1], "a23", "2024-02-20", start=FY23[0]),
                _e(15, FY23[1], "a23", "2024-02-20", start="2023-10-01"),  # Q4 only
            ],
            "CostOfRevenue": [_e(35, FY23[1], "a23", "2024-02-20", start=FY23[0])],
            "NetIncomeLoss": [_e(9, FY23[1], "a23", "2024-02-20", start=FY23[0])],
        }
    )
    t = sec.tenk_table(facts)
    assert len(t) == 1  # the 10-Q and the 10-K/A are ignored
    row = t.iloc[0]
    assert row["period_end"] == pd.Timestamp("2023-12-31")
    assert row["filed"] == pd.Timestamp("2024-02-20")
    assert (row["assets"], row["equity"], row["revenue"], row["net_income"]) == (100, 40, 60, 9)
    assert row["gross_profit"] == 25  # no GrossProfit tag: revenue - cost of revenue


def test_tenk_table_prefers_reported_gross_profit_and_handles_banks():
    facts = _facts(
        {
            "Assets": [_e(100, "2023-12-31", "a", "2024-02-20")],
            "GrossProfit": [_e(30, FY23[1], "a", "2024-02-20", start=FY23[0])],
            "Revenues": [_e(60, FY23[1], "a", "2024-02-20", start=FY23[0])],
            "CostOfRevenue": [_e(35, FY23[1], "a", "2024-02-20", start=FY23[0])],
        }
    )
    assert sec.tenk_table(facts).iloc[0]["gross_profit"] == 30
    bank = _facts({"Assets": [_e(100, "2023-12-31", "b", "2024-02-20")]})
    assert pd.isna(sec.tenk_table(bank).iloc[0]["gross_profit"])
    assert sec.tenk_table(None).empty


def test_clean_words_keeps_visible_words_only():
    raw = (
        "<html><head><title>x</title></head><ix:header><ix:hidden>secretword</ix:hidden>"
        "</ix:header><body><p>Risk&nbsp;Factors: revenue grew 12%</p>"
        "<script>var hidden=1;</script></body></html>"
    )
    assert sec.clean_words(raw) == ["risk", "factors", "revenue", "grew"]


def test_cosine_similarity():
    a = Counter({"x": 1, "y": 1})
    assert sec.cosine(a, a) == pytest.approx(1.0)
    assert sec.cosine(a, Counter({"z": 3})) == 0.0
    assert pd.isna(sec.cosine(a, Counter()))


def test_tenk_filings_keeps_original_10ks_since_date():
    subs = {
        "filings": {
            "recent": {
                "accessionNumber": ["1", "2", "3", "4"],
                "form": ["10-K", "10-K/A", "10-Q", "10-K"],
                "filingDate": ["2018-02-01", "2020-03-01", "2020-05-01", "2021-02-01"],
                "reportDate": ["2017-12-31", "2019-12-31", "2020-03-31", "2020-12-31"],
                "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm"],
            }
        }
    }
    f = sec.tenk_filings(subs, since="2019-01-01")
    assert f["accn"].tolist() == ["4"]
