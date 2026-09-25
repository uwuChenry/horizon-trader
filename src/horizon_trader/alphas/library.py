"""Alpha libraries: YAML files of formulas with their source, claimed direction, and param grid.

The direction is recorded *before* testing (from the paper's claim), so a signal that
only works with its sign flipped shows up as a negative IC instead of being quietly
reversed into a "discovery".
"""

from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from horizon_trader.alphas.dsl import fill_params, parse


class AlphaSpec(BaseModel):
    name: str
    formula: str
    direction: Literal[1, -1] = 1  # +1: higher value -> higher expected return
    params: dict[str, list[int]] = Field(default_factory=dict)
    category: str = ""
    rationale: str = ""
    reference: str = ""

    @model_validator(mode="after")
    def _formula_parses(self) -> AlphaSpec:
        for _, formula in self.variants():
            parse(formula)
        return self

    def variants(self) -> list[tuple[dict[str, int], str]]:
        """Every (params, filled formula) combination in the grid."""
        keys = list(self.params)
        combos = [dict(zip(keys, v, strict=True)) for v in product(*self.params.values())]
        return [(combo, fill_params(self.formula, combo)) for combo in combos]

    def label(self, params: dict[str, int]) -> str:
        return self.name + "".join(f" {k}={v}" for k, v in params.items())


class UnsupportedSignal(BaseModel):
    name: str
    description: str
    missing_data: str


class AlphaLibrary(BaseModel):
    source: str
    notes: str = ""
    alphas: list[AlphaSpec]
    unsupported: list[UnsupportedSignal] = Field(default_factory=list)


def load_library(path: Path | str) -> AlphaLibrary:
    with open(path, encoding="utf-8") as f:
        return AlphaLibrary.model_validate(yaml.safe_load(f))


def save_library(library: AlphaLibrary, path: Path | str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(
            library.model_dump(exclude_defaults=True), f, sort_keys=False, allow_unicode=True
        )
