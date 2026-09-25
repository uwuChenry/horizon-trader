"""Turn a research paper (PDF) into a testable alpha library with Claude.

Claude reads the PDF and returns structured JSON: formulas in our DSL, the
direction the paper claims, and a list of signals that need data we don't have.
Every formula is then parsed locally; anything that doesn't parse is moved to
`unsupported` with the parser's error rather than silently dropped or "fixed".
"""

from __future__ import annotations

import base64
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

import anthropic

from horizon_trader.alphas.dsl import FormulaError, language_reference
from horizon_trader.alphas.library import AlphaLibrary, AlphaSpec, UnsupportedSignal

DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You are a quantitative researcher. You translate the trading signals \
described in a research paper into formulas in a small formula language, so they can be \
tested independently on daily data for US large-cap stocks.

The formula language:
{language}

Rules:
- Only translate signals the paper actually describes or tests. Do not invent signals.
- Use only the fields and functions above. If a signal needs other data (fundamentals, \
market cap, shares outstanding, intraday bars, options, news, analyst estimates), put it in \
`unsupported` with what's missing. Do not approximate it with a different signal.
- `direction` is what the paper claims: 1 if higher values predict higher returns, -1 if \
lower values do. If the paper doesn't say, use 1 and say so in `rationale`.
- Keep the paper's exact windows. Only use `{{n}}`-style placeholders when the paper itself \
reports several window lengths; list those values in `params`, the paper's main one first.
- Signals are compared across stocks each day, so prefer scale-free forms when the paper's \
formula is scale-free; if the paper's formula depends on price level (e.g. CLOSE - \
DELAY(CLOSE, 14)), keep it as written and note that in `rationale`.
- `paper_quote` should be a short quote or table reference locating the signal in the paper."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "citation": {"type": "string"},
        "summary": {"type": "string"},
        "alphas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "formula": {"type": "string"},
                    "direction": {"type": "integer", "enum": [1, -1]},
                    "params": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "values": {"type": "array", "items": {"type": "integer"}},
                            },
                            "required": ["name", "values"],
                            "additionalProperties": False,
                        },
                    },
                    "category": {"type": "string"},
                    "rationale": {"type": "string"},
                    "paper_quote": {"type": "string"},
                },
                "required": [
                    "name",
                    "formula",
                    "direction",
                    "params",
                    "category",
                    "rationale",
                    "paper_quote",
                ],
                "additionalProperties": False,
            },
        },
        "unsupported": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "missing_data": {"type": "string"},
                },
                "required": ["name", "description", "missing_data"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["citation", "summary", "alphas", "unsupported"],
    "additionalProperties": False,
}


def load_pdf(source: str) -> bytes:
    """Read a local PDF, or download one (arXiv abs/html links are mapped to the PDF)."""
    if not re.match(r"https?://", source):
        return Path(source).read_bytes()
    url = re.sub(r"arxiv\.org/(abs|html)/", "arxiv.org/pdf/", source)
    request = urllib.request.Request(url, headers={"User-Agent": "horizon-trader"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if not data.startswith(b"%PDF"):
        raise ValueError(f"{url} did not return a PDF")
    return data


def request_extraction(
    client: anthropic.Anthropic, pdf: bytes, model: str = DEFAULT_MODEL
) -> dict[str, Any]:
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # retry on another model if this one declines
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
        },
        system=SYSTEM_PROMPT.format(language=language_reference()),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.standard_b64encode(pdf).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": "Extract every testable trading signal."},
                ],
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"model declined the request: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("output hit max_tokens; the paper may have too many signals")
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def to_library(raw: dict[str, Any], source: str) -> AlphaLibrary:
    """Validate each extracted formula; unparseable ones become `unsupported` entries."""
    alphas, unsupported = [], [UnsupportedSignal(**u) for u in raw["unsupported"]]
    for item in raw["alphas"]:
        try:
            alphas.append(
                AlphaSpec(
                    name=item["name"],
                    formula=item["formula"],
                    direction=item["direction"],
                    params={p["name"]: p["values"] for p in item["params"]},
                    category=item["category"],
                    rationale=item["rationale"],
                    reference=item["paper_quote"],
                )
            )
        except (FormulaError, ValueError) as e:
            unsupported.append(
                UnsupportedSignal(
                    name=item["name"],
                    description=f"{item['formula']}  ({item['rationale']})",
                    missing_data=f"formula rejected by parser: {e}",
                )
            )
    return AlphaLibrary(
        source=f"{raw['citation']} [{source}]",
        notes=raw["summary"],
        alphas=alphas,
        unsupported=unsupported,
    )


def extract(source: str, model: str = DEFAULT_MODEL) -> tuple[AlphaLibrary, dict[str, Any]]:
    raw = request_extraction(anthropic.Anthropic(), load_pdf(source), model)
    return to_library(raw, source), raw
