"""Results bundles: every backtest saves the same files, and the dashboard only reads them.

<data_dir>/results/<YYYYmmdd-HHMMSS>_<slug>/
    equity.parquet      daily equity (column "equity", date index)
    trades.parquet      one row per round trip (format in analytics.py)
    benchmark.parquet   optional benchmark price series (column "benchmark"), same dates
    meta.json           name, strategy, params, costs, caveats, oos_start, chart, git commit
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from horizon_trader.config import REPO_ROOT, data_dir

TRADE_COLUMNS = ["entry_time", "exit_time", "symbol", "side", "qty", "entry_px", "exit_px",
                 "gross", "costs", "pnl"]  # fmt: skip


def results_dir() -> Path:
    return data_dir() / "results"


def _git() -> dict[str, Any]:
    def run(*args: str) -> str:
        out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
        return out.stdout.strip()

    try:
        return {
            "git_commit": run("rev-parse", "--short", "HEAD"),
            "git_dirty": bool(run("status", "--porcelain")),
        }
    except OSError:
        return {"git_commit": None, "git_dirty": None}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def save_run(
    name: str,
    equity: pd.Series,
    trades: pd.DataFrame,
    meta: dict[str, Any] | None = None,
    benchmark: pd.Series | None = None,
) -> Path:
    missing = [c for c in TRADE_COLUMNS if c not in trades.columns]
    if missing:
        raise ValueError(f"trades missing columns {missing}")
    now = datetime.now()
    path = results_dir() / f"{now:%Y%m%d-%H%M%S}_{_slug(name)}"
    suffix = 1
    while path.exists():  # two saves in the same second
        path = path.with_name(f"{path.name}-{suffix}")
        suffix += 1
    path.mkdir(parents=True)
    equity.rename("equity").to_frame().to_parquet(path / "equity.parquet")
    trades.reset_index(drop=True).to_parquet(path / "trades.parquet", index=False)
    if benchmark is not None:
        benchmark.rename("benchmark").to_frame().to_parquet(path / "benchmark.parquet")
    info = {"name": name, "created": now.isoformat(timespec="seconds")} | _git() | (meta or {})
    info |= {"start": str(equity.index[0].date()), "end": str(equity.index[-1].date())}
    (path / "meta.json").write_text(json.dumps(info, indent=2, default=str), encoding="utf-8")
    return path


@dataclass
class Run:
    run_id: str
    meta: dict[str, Any]
    equity: pd.Series
    trades: pd.DataFrame
    benchmark: pd.Series | None


def list_runs() -> pd.DataFrame:
    rows = []
    for meta_path in sorted(results_dir().glob("*/meta.json"), reverse=True):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rows.append({"run_id": meta_path.parent.name} | {k: meta.get(k) for k in
                    ("name", "strategy", "created", "start", "end", "git_commit")})  # fmt: skip
    return pd.DataFrame(rows, columns=["run_id", "name", "strategy", "created", "start", "end",
                                       "git_commit"])  # fmt: skip


def load_run(run_id: str) -> Run:
    path = results_dir() / run_id
    bench = path / "benchmark.parquet"
    return Run(
        run_id=run_id,
        meta=json.loads((path / "meta.json").read_text(encoding="utf-8")),
        equity=pd.read_parquet(path / "equity.parquet")["equity"],
        trades=pd.read_parquet(path / "trades.parquet"),
        benchmark=pd.read_parquet(bench)["benchmark"] if bench.exists() else None,
    )
