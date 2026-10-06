"""One bounded, staged ETF research cycle; reads frozen local data only.

    python -m horizon_trader.backtest.research_cycle --stage develop
    python -m horizon_trader.backtest.research_cycle --stage validate
    python -m horizon_trader.backtest.research_cycle --stage confirm

Outputs are intentionally separate from live settings and previous experiments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from horizon_trader.backtest.research_account import AccountResult, run_account
from horizon_trader.backtest.research_stats import (
    bootstrap_diagnostics,
    choose_development,
    metrics,
    objective,
    slice_period,
)
from horizon_trader.execution.costs import ZERO_COSTS, ibkr_costs
from horizon_trader.sleeves.research_cycle import build_cycle_sleeve

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config/experiments/research_cycle_2026_10_01.yaml"
INPUTS = ROOT / "data/research_cycle_2026_10_01/inputs"
REPORT = ROOT / "research/cycle_2026_10_01"
RESULTS = REPORT / "results"
REFERENCE = "qqq_total_return"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def load_inputs(config: dict) -> tuple[dict[str, pd.DataFrame], pd.Series]:
    manifest = json.loads((INPUTS / "manifest.json").read_text(encoding="utf-8"))
    for entry in [*manifest["symbols"], manifest["funding"]]:
        path = ROOT / entry["file"].replace("\\", "/")
        if sha(path) != entry["sha256"]:
            raise ValueError(f"Frozen input hash mismatch: {path}")
    files = {s: pd.read_parquet(INPUTS / f"{s}.parquet") for s in config["symbols"]}
    panels = {
        col: pd.DataFrame({s: df[col] for s, df in files.items()}).sort_index().loc[: config["end"]]
        for col in ["adjusted_open", "adjusted_close", "raw_open", "raw_close"]
    }
    # Require complete common sessions AFTER the evaluation start; no forward fills.
    for col, panel in panels.items():
        if panel.loc[config["initial_nav_date"] :].isna().any().any():
            raise ValueError(f"Incomplete prices in {col}")
    return panels, pd.read_parquet(INPUTS / "dff.parquet")["ff"]


def evaluate(spec, panels, rates, config, *, start=None, end=None, stress=None):
    start = start or config["initial_nav_date"]
    end = end or config["end"]
    prices = panels["adjusted_close"].loc[:end]
    targets = build_cycle_sleeve(spec).decision_history(prices, start)
    return evaluate_targets(targets, panels, rates, config, stress=stress)


def evaluate_targets(targets, panels, rates, config, *, stress=None):
    stress = stress or {}
    idx = targets.index
    return run_account(
        targets,
        panels["adjusted_open"].loc[idx],
        panels["adjusted_close"].loc[idx],
        panels["raw_open"].loc[idx],
        rates.reindex(idx, method="ffill"),
        starting_cash=config["starting_cash"],
        costs=ZERO_COSTS
        if stress.get("zero_transaction_costs")
        else ibkr_costs(
            stress.get("plan", config["cost_plan"]),
            stress.get("slippage_bps", config["slippage_bps"]),
        ),
        delay=stress.get("delay", 1),
        whole_shares=stress.get("whole_shares", True),
        borrow_spread=stress.get("borrow_spread", config["borrow_spread"]),
        cash_rate_mode=stress.get("cash_rate_mode", "zero"),
    )


def ideal_qqq(panels, config, *, start=None, end=None):
    """Fully invested gross QQQ TR from the SAME first eligible opening session."""
    start = start or config["initial_nav_date"]
    end = end or config["end"]
    idx = panels["adjusted_close"].loc[start:end].index
    equity = config["starting_cash"] * panels["adjusted_close"].loc[idx, "QQQ"]
    equity /= panels["adjusted_open"].loc[idx[1], "QQQ"]
    equity.iloc[0] = config["starting_cash"]
    daily = pd.DataFrame(
        0.0,
        index=idx,
        columns=[
            "equity",
            "cash",
            "gross_exposure",
            "open_gross_exposure",
            "qqq_exposure",
            "turnover",
            "order_count",
            "fees",
            "slippage",
            "borrow_cost",
            "cash_income",
            "margin_breach",
            "cash_clipped",
        ],
    )
    daily["equity"] = equity
    daily.loc[idx[1] :, ["gross_exposure", "open_gross_exposure", "qqq_exposure"]] = 1.0
    daily.loc[idx[1], ["turnover", "order_count"]] = 1.0
    daily.loc[idx[0], "cash"] = config["starting_cash"]
    return AccountResult(daily=daily, trades=pd.DataFrame())


def table_for(results, rates, periods):
    rows = []
    reference = results[REFERENCE].daily.equity
    for label, (start, end) in periods.items():
        period_rows = {}
        for name, result in results.items():
            daily = slice_period(result.daily, start, end)
            period_rows[name] = metrics(daily, rates, reference)
        for name, row in period_rows.items():
            passed, gap, reduction = objective(row, period_rows[REFERENCE])
            rows.append(
                {
                    "period": label,
                    "strategy": name,
                    **row,
                    "objective_pass": passed,
                    "cagr_gap": gap,
                    "dd_reduction": reduction,
                }
            )
    return pd.DataFrame(rows)


def persist_runs(results, prefix):
    equities = pd.DataFrame({name: r.daily.equity for name, r in results.items()})
    equities.to_csv(RESULTS / f"{prefix}_equity.csv", index_label="date")
    (equities / equities.cummax() - 1).to_csv(
        RESULTS / f"{prefix}_drawdown.csv", index_label="date"
    )
    trades = []
    for name, r in results.items():
        r.daily.to_parquet(RESULTS / f"{prefix}_{name}_daily.parquet")
        if not r.trades.empty:
            trades.append(r.trades.assign(strategy=name))
    if trades:
        pd.concat(trades, ignore_index=True).to_csv(RESULTS / f"{prefix}_trades.csv", index=False)


def locked_selection(config_path):
    selection_path = RESULTS / "selection.json"
    if not selection_path.exists():
        raise ValueError("Run development and freeze selection first")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection["config_sha256"] != sha(config_path):
        raise ValueError("Configuration changed since selection: create a separate cycle")
    if selection["protocol_sha256"] != sha(REPORT / "protocol.md"):
        raise ValueError("Protocol changed since selection: create a separate cycle")
    return selection


def develop(config, config_path, panels, rates):
    results = {
        s["name"]: evaluate(s, panels, rates, config, end=config["development_end"])
        for s in config["variants"] + config["controls"]
    }
    results[REFERENCE] = ideal_qqq(panels, config, end=config["development_end"])
    table = table_for(results, rates, {"development": ("2007-01-01", config["development_end"])})
    names = [s["name"] for s in config["variants"]]
    selection = choose_development(table.set_index("strategy"), names, REFERENCE)
    central = [s["name"] for s in config["variants"] if s.get("central")]
    selection["matched_weights"] = {
        name: float(table.set_index("strategy").loc[name, "mean_exposure"])
        for name in sorted(set(central + [selection["selected"]]))
    }
    selection |= {
        "config_sha256": sha(config_path),
        "protocol_sha256": sha(REPORT / "protocol.md"),
        "written_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "development_end": config["development_end"],
        "holdout_status": "No untouched holdout; historical validation and confirmation reused",
    }
    path = RESULTS / "selection.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        for key in ["selected", "matched_weights", "config_sha256", "protocol_sha256"]:
            if old[key] != selection[key]:
                raise ValueError("Rerun would change locked selection; use a separate cycle")
    else:
        write_json(path, selection)
    table.to_csv(RESULTS / "development_metrics.csv", index=False)
    persist_runs(results, "development")
    print(
        table[["strategy", "cagr", "max_drawdown", "sharpe", "objective_pass"]].to_string(
            index=False
        )
    )
    print("Locked:", selection["selected"], "matched controls:", selection["matched_weights"])


def specs_with_controls(config, selection):
    specs = config["variants"] + config["controls"]
    return specs + [
        {"name": f"matched_{name}", "family": "static", "weight": min(weight, 1.5)}
        for name, weight in selection["matched_weights"].items()
    ]


def validate(config, config_path, panels, rates):
    selection = locked_selection(config_path)
    specs = specs_with_controls(config, selection)
    results = {
        s["name"]: evaluate(s, panels, rates, config, end=config["validation_end"]) for s in specs
    }
    results[REFERENCE] = ideal_qqq(panels, config, end=config["validation_end"])
    table = table_for(results, rates, {"validation": ("2016-01-01", config["validation_end"])})
    table.to_csv(RESULTS / "validation_metrics.csv", index=False)
    persist_runs(results, "validation")
    print(
        table[["strategy", "cagr", "max_drawdown", "sharpe", "objective_pass"]].to_string(
            index=False
        )
    )
    write_json(
        RESULTS / "validation_complete.json",
        {
            "selected": selection["selected"],
            "written_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "no_retuning": True,
        },
    )


def walk_forward(specs, results, panels, rates, config):
    """Annual expanding dev selector; replay selected decisions in one real account."""
    targets = pd.DataFrame(np.nan, index=results[REFERENCE].daily.index, columns=config["symbols"])
    histories = {
        s["name"]: build_cycle_sleeve(s).decision_history(
            panels["adjusted_close"], config["initial_nav_date"]
        )
        for s in specs
    }
    choices = []
    names = [s["name"] for s in specs]
    selected = None
    for year in range(2016, 2027):
        train_end = f"{year - 1}-12-31"
        table = table_for(
            {k: v for k, v in results.items() if k in names + [REFERENCE]},
            rates,
            {"training": ("2007-01-01", train_end)},
        ).set_index("strategy")
        pick = choose_development(table, names, REFERENCE)
        selected = pick["selected"]
        idx = targets.index[(targets.index.year == year)]
        if len(idx) == 0:
            continue
        targets.loc[idx] = histories[selected].loc[idx]
        # Choose after the prior year's last close; first new-year open is eligible.
        prior = targets.index[targets.index.get_loc(idx[0]) - 1]
        daily = build_cycle_sleeve(next(s for s in specs if s["name"] == selected))
        targets.loc[prior] = daily.daily_signal(panels["adjusted_close"].loc[:prior]).iloc[-1]
        choices.append({"year": year, "training_end": train_end, **pick})
    first = targets.index[targets.index < "2016-01-01"][-1]
    wf = evaluate_targets(targets.loc[first:], panels, rates, config)
    return wf, pd.DataFrame(choices)


def confirm(config, config_path, panels, rates):
    selection = locked_selection(config_path)
    if not (RESULTS / "validation_complete.json").exists():
        raise ValueError("Run chronological validation before final historical batch")
    specs = specs_with_controls(config, selection)
    results = {s["name"]: evaluate(s, panels, rates, config) for s in specs}
    results[REFERENCE] = ideal_qqq(panels, config)
    periods = {
        "full": ("2007-01-01", config["end"]),
        "development": ("2007-01-01", config["development_end"]),
        "validation": ("2016-01-01", config["validation_end"]),
        "confirmation_reused": ("2021-01-01", config["end"]),
        "later_combined": ("2016-01-01", config["end"]),
        "financial_crisis": ("2007-01-01", "2009-12-31"),
        "recovery": ("2010-01-01", "2015-12-31"),
        "pre_covid": ("2016-01-01", "2019-12-31"),
        "covid": ("2020-01-01", "2020-12-31"),
        "2021": ("2021-01-01", "2021-12-31"),
        "inflation_2022": ("2022-01-01", "2022-12-31"),
        "recent": ("2023-01-01", config["end"]),
    }
    table = table_for(results, rates, periods)
    table.to_csv(RESULTS / "metrics.csv", index=False)
    persist_runs(results, "full")
    central = [s["name"] for s in config["variants"] if s.get("central")]
    focus = set(central + [selection["selected"], "qqq_buy_hold", "qqq_125", "qqq_vol_only"])
    focus |= {s["name"] for s in specs if s["name"].startswith("matched_")}
    stress_rows = []
    for stress in [
        *config["stress"],
        {"name": "zero_transaction_costs", "zero_transaction_costs": True},
    ]:
        stressed = {
            s["name"]: evaluate(s, panels, rates, config, stress=stress)
            for s in specs
            if s["name"] in focus
        }
        # Fixed ideal reference: delays should bear the opportunity cost of waiting.
        stressed[REFERENCE] = results[REFERENCE]
        t = table_for(
            stressed, rates, {k: periods[k] for k in ["full", "validation", "confirmation_reused"]}
        )
        stress_rows.append(t.assign(scenario=stress["name"]))
        if stress["name"] == "joint_adverse":
            persist_runs(stressed, "joint_adverse")
    pd.concat(stress_rows, ignore_index=True).to_csv(RESULTS / "stress_metrics.csv", index=False)

    restarts = []
    for label, start in [
        ("validation_5k_restart", "2015-12-31"),
        ("confirmation_5k_restart", "2020-12-31"),
    ]:
        end = config["validation_end"] if "validation" in label else config["end"]
        fresh = {
            s["name"]: evaluate(s, panels, rates, config, start=start, end=end)
            for s in specs
            if s["name"] in focus
        }
        fresh[REFERENCE] = ideal_qqq(panels, config, start=start, end=end)
        restarts.append(
            table_for(fresh, rates, {label: (str(fresh[REFERENCE].daily.index[1].date()), end)})
        )
    pd.concat(restarts, ignore_index=True).to_csv(RESULTS / "restart_metrics.csv", index=False)

    wf, choices = walk_forward(config["variants"], results, panels, rates, config)
    wf_reference = ideal_qqq(panels, config, start="2015-12-31")
    table_for(
        {"annual_selector": wf, REFERENCE: wf_reference},
        rates,
        {"walk_forward": ("2016-01-01", config["end"])},
    ).to_csv(RESULTS / "walk_forward_metrics.csv", index=False)
    choices.to_csv(RESULTS / "walk_forward_choices.csv", index=False)
    persist_runs({"annual_selector": wf, REFERENCE: wf_reference}, "walk_forward")

    # Predeclared dotcom diagnostic; no nonexistent gold/Treasury prices are imputed.
    qpanels = {k: v[["QQQ"]].dropna() for k, v in panels.items()}
    dotcom_specs = [
        s for s in specs if s["family"] in {"trend", "voltrend", "vol_only", "buy_hold", "static"}
    ]
    early = {
        s["name"]: evaluate(s, qpanels, rates, config, start="2000-12-29", end="2006-12-29")
        for s in dotcom_specs
        if s["name"] in focus or s.get("central")
    }
    early[REFERENCE] = ideal_qqq(qpanels, config, start="2000-12-29", end="2006-12-29")
    table_for(early, rates, {"dotcom_reused": ("2001-01-01", "2006-12-29")}).to_csv(
        RESULTS / "dotcom_metrics.csv", index=False
    )

    equities = pd.DataFrame({name: r.daily.equity for name, r in results.items()})
    daily_returns = equities.pct_change().loc["2016-01-01":]
    bootstrap_diagnostics(
        daily_returns,
        REFERENCE,
        [s["name"] for s in config["variants"]],
        samples=config["bootstrap_samples"],
        block=config["bootstrap_block_days"],
        seed=config["seed"],
    ).to_csv(RESULTS / "uncertainty.csv", index=False)
    year_rows = []
    for year in range(2007, 2027):
        year_rows.append(table_for(results, rates, {str(year): (f"{year}-01-01", f"{year}-12-31")}))
    pd.concat(year_rows, ignore_index=True).to_csv(RESULTS / "yearly_metrics.csv", index=False)
    print(
        table[table.period.isin(["full", "validation", "confirmation_reused"])][
            ["period", "strategy", "cagr", "max_drawdown", "objective_pass"]
        ].to_string(index=False)
    )
    write_json(
        RESULTS / "confirmation_complete.json",
        {
            "selected": selection["selected"],
            "written_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "selection_unchanged": True,
            "holdout": "reused historical confirmation",
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--stage", choices=["develop", "validate", "confirm"], required=True)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    RESULTS.mkdir(parents=True, exist_ok=True)
    panels, rates = load_inputs(config)
    manifest = {
        "stage": args.stage,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "config_sha256": sha(args.config),
        "input_manifest_sha256": sha(INPUTS / "manifest.json"),
        "code_hashes": {
            str(path.relative_to(ROOT)): sha(path)
            for path in [
                Path(__file__),
                Path(__file__).with_name("research_account.py"),
                Path(__file__).with_name("research_stats.py"),
                ROOT / "src/horizon_trader/sleeves/research_cycle.py",
            ]
        },
        "timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    write_json(RESULTS / f"{args.stage}_manifest.json", manifest)
    {"develop": develop, "validate": validate, "confirm": confirm}[args.stage](
        config, args.config, panels, rates
    )


if __name__ == "__main__":
    main()
