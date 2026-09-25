"""Robustness checks, so a good backtest isn't mistaken for a good strategy.

1. Parameter sensitivity: rerun each sleeve over a grid around its configured params.
   A real edge shows a plateau (neighboring params perform similarly); an isolated
   spike means the result is fitted noise.
2. Sub-period stability: Sharpe in the first vs second half of the sample.
3. Walk-forward: each year, pick the grid params with the best Sharpe over the prior
   `train_years`, trade them for that year only, and stitch the out-of-sample years.
   If this can't beat the fixed a-priori params, tuning adds nothing but false confidence.
4. Correlation of sleeve returns: combining sleeves only helps if they're not the same bet.

    uv run python -m horizon_trader.backtest.robustness
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from itertools import groupby, product
from pathlib import Path
from typing import Any

import pandas as pd

from horizon_trader.backtest.metrics import sharpe, summarize
from horizon_trader.backtest.run import (
    BENCHMARK,
    BENCHMARK_LABEL,
    format_report,
    load_universe_bars,
    run_targets,
    standalone_risk,
)
from horizon_trader.backtest.sim import BacktestResult
from horizon_trader.config import DEFAULT_CONFIG, Settings, SleeveSettings, load_settings
from horizon_trader.portfolio import apply_risk_limits
from horizon_trader.sleeves import build_sleeve
from horizon_trader.sleeves.static import StaticSleeve

PARAM_GRIDS: dict[str, dict[str, list[Any]]] = {
    "momentum_rotation": {"lookback": [126, 189, 252], "top_n": [2, 3, 4]},
    "trend_following": {"lookback": [126, 189, 252], "vol_window": [21, 63]},
    "vol_managed": {"target_vol": [0.10, 0.15, 0.20], "window": [21, 63]},
    "mean_reversion": {"entry": [5, 10, 15], "exit": [60, 70, 80]},
    "macd": {"fast": [8, 12, 16], "slow": [21, 26, 39]},
}

Bars = dict[str, pd.DataFrame]


@dataclass
class GridRun:
    params: dict[str, Any]
    targets: pd.DataFrame
    result: BacktestResult


def _targets(name: str, cfg: SleeveSettings, settings: Settings, bars: Bars) -> pd.DataFrame:
    weights = build_sleeve(name, cfg).weights_history(bars["close"])
    return apply_risk_limits(weights, standalone_risk(settings))


def grid_runs(
    name: str, cfg: SleeveSettings, settings: Settings, bars: Bars, start: str
) -> list[GridRun]:
    grid = PARAM_GRIDS.get(cfg.type, {})
    runs = []
    for values in product(*grid.values()):
        combo = dict(zip(grid, values, strict=True))
        variant = cfg.model_copy(update={"params": cfg.params | combo})
        targets = _targets(name, variant, settings, bars)
        runs.append(GridRun(combo, targets, run_targets(targets, bars, start, settings)))
    return runs


def is_configured(run: GridRun, cfg: SleeveSettings) -> bool:
    return all(cfg.params.get(k) == v for k, v in run.params.items())


def sensitivity_table(runs: list[GridRun], cfg: SleeveSettings) -> pd.DataFrame:
    equity0 = runs[0].result.equity
    split = equity0.index[len(equity0) // 2]
    rows = []
    for run in runs:
        eq = run.result.equity
        stats = summarize(eq, run.result.trades)
        rows.append(
            {
                **run.params,
                "CAGR": stats["CAGR"],
                "Sharpe": stats["Sharpe"],
                "max DD": stats["max DD"],
                f"Sharpe <{split.year}": sharpe(eq.loc[:split]),
                f"Sharpe >={split.year}": sharpe(eq.loc[split:]),
                "trades/yr": stats["trades/yr"],
                "cfg": "*" if is_configured(run, cfg) else "",
            }
        )
    return pd.DataFrame(rows)


def walk_forward(
    runs: list[GridRun], bars: Bars, settings: Settings, train_years: int
) -> tuple[BacktestResult, list[tuple[int, dict[str, Any]]]]:
    years = sorted(set(runs[0].result.equity.index.year))
    test_years = years[train_years:]
    pieces, picks = [], []
    for year in test_years:
        train = slice(str(year - train_years), str(year - 1))
        best = max(runs, key=lambda r: sharpe(r.result.equity.loc[train]))
        pieces.append(best.targets.loc[str(year)])
        picks.append((year, best.params))
    return run_targets(pd.concat(pieces), bars, str(test_years[0]), settings), picks


def _describe_picks(picks: list[tuple[int, dict[str, Any]]]) -> str:
    spans = []
    for params, group in groupby(picks, key=lambda p: tuple(p[1].items())):
        yrs = [y for y, _ in group]
        label = f"{yrs[0]}" if len(yrs) == 1 else f"{yrs[0]}-{yrs[-1]}"
        spans.append(f"{label}: " + ", ".join(f"{k}={v}" for k, v in params))
    return "\n    ".join(spans)


def _fmt(equity: pd.Series) -> str:
    return f"Sharpe {sharpe(equity):.2f}, CAGR {summarize(equity)['CAGR']:.1%}"


def analyze_sleeve(
    name: str, cfg: SleeveSettings, settings: Settings, bars: Bars, start: str, train_years: int
) -> BacktestResult:
    """Print the sensitivity grid and walk-forward comparison; return the configured run."""
    runs = grid_runs(name, cfg, settings, bars, start)
    configured = next((r for r in runs if is_configured(r, cfg)), None)
    if configured is None:
        targets = _targets(name, cfg, settings, bars)
        configured = GridRun(cfg.params, targets, run_targets(targets, bars, start, settings))

    print(f"\n=== {name} ({cfg.type}) ===")
    if len(runs) > 1:
        table = sensitivity_table(runs, cfg)
        print(format_report(table))
        rank = int((table["Sharpe"] > table.loc[table["cfg"] == "*", "Sharpe"].max()).sum()) + 1
        q = table["Sharpe"].quantile([0, 0.5, 1]).tolist()
        print(
            f"configured params rank {rank}/{len(runs)} by Sharpe; "
            f"grid Sharpe min {q[0]:.2f} / median {q[1]:.2f} / max {q[2]:.2f}"
        )

        wf, picks = walk_forward(runs, bars, settings, train_years)
        oos_start = str(picks[0][0])
        fixed = run_targets(configured.targets, bars, oos_start, settings)
        print(f"walk-forward out-of-sample {oos_start}+ (train on prior {train_years}y):")
        print(f"  re-tuned yearly: {_fmt(wf.equity)}")
        print(f"  fixed config:    {_fmt(fixed.equity)}")
        print(f"  picks:\n    {_describe_picks(picks)}")
    return configured.result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--start", default="2008-01-01")
    parser.add_argument("--train-years", type=int, default=5)
    parser.add_argument("--sleeve", action="append", help="only analyze these sleeves")
    args = parser.parse_args()

    settings = load_settings(args.config)
    bars = load_universe_bars(settings)
    print(f"IBKR {settings.costs.plan} pricing, {settings.costs.slippage_bps:g} bps slippage")

    returns = {}
    for name, cfg in settings.sleeves.items():
        if args.sleeve and name not in args.sleeve:
            continue
        result = analyze_sleeve(name, cfg, settings, bars, args.start, args.train_years)
        returns[name] = result.equity.pct_change()

    benchmark = StaticSleeve("benchmark", {BENCHMARK: 1.0}).weights_history(bars["close"])
    returns[BENCHMARK_LABEL] = run_targets(
        benchmark, bars, args.start, settings
    ).equity.pct_change()
    print("\n=== correlation of daily returns ===")
    print(pd.DataFrame(returns).corr().round(2).to_string())


if __name__ == "__main__":
    main()
