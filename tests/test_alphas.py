import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from horizon_trader.alphas.dsl import FUNCTIONS, FormulaError, evaluate, fields_used, parse
from horizon_trader.alphas.evaluate import evaluate_library, forward_returns, rank_ic
from horizon_trader.alphas.extract import request_extraction, to_library
from horizon_trader.alphas.library import AlphaLibrary, AlphaSpec, load_library, save_library
from horizon_trader.sleeves.alpha import AlphaSleeve


@pytest.fixture
def bars():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2018-01-01", periods=400)
    cols = [f"S{i:02d}" for i in range(30)]
    close = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0.0003, 0.015, (len(idx), 30)), axis=0), idx, cols
    )
    noise = pd.DataFrame(rng.uniform(0.0, 0.01, close.shape), idx, cols)
    return {
        "open": close.shift(1).fillna(close),
        "high": close * (1 + noise),
        "low": close * (1 - noise),
        "close": close,
        "volume": pd.DataFrame(rng.integers(1_000, 10_000, close.shape), idx, cols),
    }


# --- formula language -------------------------------------------------------------


def test_evaluates_like_hand_written_pandas(bars):
    got = evaluate("DELAY(CLOSE, 21) / DELAY(CLOSE, 252) - 1", bars)
    close = bars["close"]
    pd.testing.assert_frame_equal(got, close.shift(21) / close.shift(252) - 1)
    ranked = evaluate("RANK(RETURNS)", bars)
    assert ranked.max().max() == pytest.approx(1.0)


def test_aliases_and_fields(bars):
    pd.testing.assert_frame_equal(
        evaluate("MAX(HIGH, 20)", bars), evaluate("TS_MAX(HIGH, 20)", bars)
    )
    assert fields_used("CORR(CLOSE, VOLUME, 21) * RSI(CLOSE, 14)") == {"CLOSE", "VOLUME"}


@pytest.mark.parametrize(
    "formula",
    [
        "__import__('os').system('echo pwned')",
        "CLOSE.shift(-1)",
        "open('secrets.txt')",
        "[CLOSE for _ in range(3)]",
        "lambda: CLOSE",
        "PRICE / 2",
        "DELAY(CLOSE, -5)",  # negative delay = lookahead
        "DELAY(CLOSE, 0.5)",
        "MA(CLOSE, n)",
        "MA(CLOSE)",
        "MA(CLOSE, 20, 3)",
        "CLOSE[0]",
    ],
)
def test_rejects_anything_outside_the_language(formula):
    with pytest.raises(FormulaError):
        parse(formula)


def test_constant_formula_is_not_a_signal(bars):
    with pytest.raises(FormulaError):
        evaluate("1 + 2", bars)


def test_division_by_zero_becomes_nan(bars):
    assert not np.isinf(evaluate("CLOSE / (CLOSE - CLOSE)", bars).to_numpy()).any()


@pytest.mark.parametrize("fn", sorted(FUNCTIONS))
def test_every_function_is_causal(fn, bars):
    """Cutting off the future never changes today's value, for every function."""
    spec = FUNCTIONS[fn].args
    args = ", ".join(
        {"x": "CLOSE", "n": "10"}[a] if i == 0 or a == "n" else "VOLUME" for i, a in enumerate(spec)
    )
    formula = f"{fn}({args})"
    full = evaluate(formula, bars)
    t = 250
    cut = evaluate(formula, {k: v.iloc[: t + 1] for k, v in bars.items()})
    pd.testing.assert_series_equal(full.iloc[t], cut.iloc[-1])


# --- evaluation ---------------------------------------------------------------------


def test_perfect_foresight_alpha_has_ic_one(bars):
    fwd = forward_returns(bars["close"], 5)
    ic = rank_ic(fwd, fwd)
    assert ic.mean() == pytest.approx(1.0)
    assert rank_ic(-fwd, fwd).mean() == pytest.approx(-1.0)


def test_direction_flips_the_sign(bars):
    lib = AlphaLibrary(
        source="t",
        alphas=[
            AlphaSpec(name="up", formula="RETURNS", direction=1),
            AlphaSpec(name="down", formula="RETURNS", direction=-1),
        ],
    )
    table = evaluate_library(lib, bars, "2018-01-01", "2019-01-01", horizon=1)
    assert table.loc["up", "IC 1d"] == pytest.approx(-table.loc["down", "IC 1d"])


def test_research_labels_never_use_holdout_prices(bars):
    """Changing prices after the holdout start must not move research numbers."""
    lib = AlphaLibrary(source="t", alphas=[AlphaSpec(name="r", formula="RETURNS")])
    before = evaluate_library(lib, bars, "2018-01-01", "2019-03-01")
    shocked = {k: v.copy() for k, v in bars.items()}
    shocked["close"].loc["2019-03-01":] *= 3.0
    after = evaluate_library(lib, shocked, "2018-01-01", "2019-03-01")
    pd.testing.assert_frame_equal(before, after)


# --- library & extraction ---------------------------------------------------------


def test_param_grid_expands_and_roundtrips(tmp_path):
    spec = AlphaSpec(name="lv", formula="STD(RETURNS, {n})", direction=-1, params={"n": [20, 60]})
    assert [f for _, f in spec.variants()] == ["STD(RETURNS, 20)", "STD(RETURNS, 60)"]
    lib = AlphaLibrary(source="s", alphas=[spec])
    save_library(lib, tmp_path / "lib.yaml")
    assert load_library(tmp_path / "lib.yaml") == lib


def test_invalid_formula_rejected_at_load():
    with pytest.raises(ValueError):
        AlphaSpec(name="bad", formula="EPS / DELAY(EPS, 1)")


RAW = {
    "citation": "Doe (2026)",
    "summary": "Two signals.",
    "alphas": [
        {
            "name": "mom",
            "formula": "CLOSE / DELAY(CLOSE, {n}) - 1",
            "direction": 1,
            "params": [{"name": "n", "values": [126, 252]}],
            "category": "momentum",
            "rationale": "trend",
            "paper_quote": "Table 2",
        },
        {
            "name": "eps_growth",
            "formula": "EPS / DELAY(EPS, 63) - 1",
            "direction": 1,
            "params": [],
            "category": "fundamental",
            "rationale": "growth",
            "paper_quote": "Sec 3",
        },
    ],
    "unsupported": [{"name": "news", "description": "headline tone", "missing_data": "news"}],
}


def test_unparseable_extracted_formulas_move_to_unsupported():
    lib = to_library(RAW, "paper.pdf")
    assert [a.name for a in lib.alphas] == ["mom"]
    assert lib.alphas[0].params == {"n": [126, 252]}
    assert {u.name for u in lib.unsupported} == {"news", "eps_growth"}
    assert "parser" in next(u for u in lib.unsupported if u.name == "eps_growth").missing_data


def test_request_extraction_sends_pdf_and_parses_json():
    calls = {}

    def create(**kwargs):
        calls.update(kwargs)
        text = SimpleNamespace(type="text", text=json.dumps(RAW))
        return SimpleNamespace(stop_reason="end_turn", content=[text])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    assert request_extraction(client, b"%PDF-1.7 fake") == RAW
    doc = calls["messages"][0]["content"][0]
    assert doc["type"] == "document" and doc["source"]["media_type"] == "application/pdf"
    assert calls["output_config"]["format"]["type"] == "json_schema"
    assert "DELAY(x, n)" in calls["system"]  # the language spec is in the prompt


def test_refusal_is_an_error_not_empty_output():
    refused = SimpleNamespace(stop_reason="refusal", stop_details="x", content=[])
    client = SimpleNamespace(
        beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **_: refused))
    )
    with pytest.raises(RuntimeError):
        request_extraction(client, b"%PDF")


# --- sleeve -----------------------------------------------------------------------


def test_alpha_sleeve_holds_top_n_and_has_no_lookahead(bars):
    sleeve = AlphaSleeve("hi52", "CLOSE / TS_MAX(HIGH, 60)", top_n=5, bars_loader=lambda _s: bars)
    full = sleeve.weights_history(bars["close"])
    assert ((full > 0).sum(axis=1).iloc[100:] == 5).all()
    for t in (150, 300, 399):
        cut = sleeve.weights_history(bars["close"].iloc[: t + 1])
        pd.testing.assert_series_equal(full.iloc[t], cut.iloc[-1])
