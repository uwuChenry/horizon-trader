"""Backtest every sleeve alone, the combined book, and SPY buy-and-hold, with IBKR-style costs.

uv run python -m horizon_trader.backtest.run --start 2008-01-01
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from horizon_trader.backtest.metrics import summarize
from horizon_trader.backtest.sim import BacktestResult, simulate
from horizon_trader.config import DEFAULT_CONFIG, RiskSettings, Settings, load_settings
from horizon_trader.data.store import load_bars
from horizon_trader.execution.costs import ibkr_costs
from horizon_trader.portfolio import apply_risk_limits, combine_history
from horizon_trader.sleeves import build_sleeve
from horizon_trader.sleeves.static import StaticSleeve

BENCHMARK = "SPY"
BENCHMARK_LABEL = f"{BENCHMARK} buy&hold"


def standalone_risk(settings: Settings) -> RiskSettings:
    """A sleeve run on its own keeps the gross limit but not the per-name cap, which is
    a property of the combined book (e.g. a single-ETF sleeve would otherwise be capped)."""
    return RiskSettings(max_weight=1.0, max_gross=settings.risk.max_gross)


def target_histories(settings: Settings, closes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Target weights per run: the combined book, each sleeve on its own, and the benchmark."""
    histories = {
        name: build_sleeve(name, cfg).weights_history(closes)
        for name, cfg in settings.sleeves.items()
    }
    allocations = {name: cfg.allocation for name, cfg in settings.sleeves.items()}
    alone = standalone_risk(settings)
    runs = {"combined": apply_risk_limits(combine_history(histories, allocations), settings.risk)}
    runs |= {name: apply_risk_limits(h, alone) for name, h in histories.items()}
    runs[BENCHMARK_LABEL] = StaticSleeve("benchmark", {BENCHMARK: 1.0}).weights_history(closes)
    return runs


def load_universe_bars(settings: Settings, refresh: bool = False) -> dict[str, pd.DataFrame]:
    return load_bars(sorted(set(settings.universe) | {BENCHMARK}), refresh=refresh)


def run_targets(
    targets: pd.DataFrame, bars: dict[str, pd.DataFrame], start: str, settings: Settings
) -> BacktestResult:
    return simulate(
        targets.loc[start:],
        bars["open"].loc[start:],
        bars["close"].loc[start:],
        settings.account.starting_cash,
        settings.execution,
        ibkr_costs(settings.costs.plan, settings.costs.slippage_bps),
    )


def backtest(settings: Settings, start: str, refresh: bool = False) -> dict[str, BacktestResult]:
    bars = load_universe_bars(settings, refresh)
    # Signals use full history so indicators are warmed up by `start`.
    runs = target_histories(settings, bars["close"])
    return {label: run_targets(targets, bars, start, settings) for label, targets in runs.items()}


def report(results: dict[str, BacktestResult]) -> pd.DataFrame:
    return pd.DataFrame({k: summarize(r.equity, r.trades) for k, r in results.items()}).T


def format_report(table: pd.DataFrame) -> str:
    out = table.copy().astype(object)
    for col in table.columns:
        if col in ("CAGR", "vol", "max DD"):
            out[col] = table[col].map("{:.1%}".format)
        elif col in ("final", "commissions"):
            out[col] = table[col].map("${:,.0f}".format)
        elif pd.api.types.is_float_dtype(table[col]):
            out[col] = table[col].map("{:.2f}".format)
    return out.to_string()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--start", default="2008-01-01")
    parser.add_argument("--refresh", action="store_true", help="re-download cached bars")
    parser.add_argument("--plan", choices=["fixed", "tiered"], help="override IBKR pricing plan")
    args = parser.parse_args()

    settings = load_settings(args.config)
    if args.plan:
        settings.costs.plan = args.plan
    print(f"IBKR {settings.costs.plan} pricing, {settings.costs.slippage_bps:g} bps slippage")
    print(format_report(report(backtest(settings, args.start, args.refresh))))


if __name__ == "__main__":
    main()
