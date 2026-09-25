"""Settings loading. All paths go through pathlib so the same config works on Windows and Linux."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "settings.yaml"

load_dotenv(REPO_ROOT / ".env")


class AccountSettings(BaseModel):
    starting_cash: float = 5_000.0


class SleeveSettings(BaseModel):
    type: str
    allocation: float = Field(ge=0.0, le=1.0)
    params: dict[str, Any] = Field(default_factory=dict)


class RiskSettings(BaseModel):
    max_weight: float = Field(0.25, gt=0.0, le=1.0)
    max_gross: float = Field(1.0, gt=0.0)


class ExecutionSettings(BaseModel):
    min_trade_value: float = 25.0
    rebalance_band: float = Field(0.02, ge=0.0)
    share_decimals: int = 4


class CostSettings(BaseModel):
    plan: Literal["fixed", "tiered"] = "fixed"
    slippage_bps: float = Field(5.0, ge=0.0)


class Settings(BaseModel):
    account: AccountSettings = AccountSettings()
    universe: list[str]
    sleeves: dict[str, SleeveSettings]
    risk: RiskSettings = RiskSettings()
    execution: ExecutionSettings = ExecutionSettings()
    costs: CostSettings = CostSettings()

    @model_validator(mode="after")
    def _allocations_fit(self) -> Settings:
        total = sum(s.allocation for s in self.sleeves.values())
        if total > 1.0 + 1e-9:
            raise ValueError(f"sleeve allocations sum to {total:.3f} > 1.0")
        return self


def load_settings(path: Path | str = DEFAULT_CONFIG) -> Settings:
    with open(path, encoding="utf-8") as f:
        return Settings.model_validate(yaml.safe_load(f))


def data_dir() -> Path:
    """Root for Parquet/SQLite state: $HT_DATA_DIR if set, else ./data in the repo."""
    path = Path(os.environ.get("HT_DATA_DIR") or REPO_ROOT / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path
