"""Paper -> formulas -> evidence.

    uv run python -m horizon_trader.alphas.cli extract https://arxiv.org/pdf/2409.06289
    uv run python -m horizon_trader.alphas.cli evaluate research/alphas/classics.yaml
    uv run python -m horizon_trader.alphas.cli backtest research/alphas/classics.yaml mom_12_1

Discipline built in: everything reports on the research period (default 2010-2023)
unless you pass --holdout. Look at the holdout once, after you've picked a shortlist;
every extra peek turns it into more research data.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd
import yaml

from horizon_trader.alphas.evaluate import evaluate_library
from horizon_trader.alphas.library import AlphaLibrary, load_library, save_library
from horizon_trader.backtest.metrics import summarize
from horizon_trader.backtest.run import format_report
from horizon_trader.backtest.sim import simulate
from horizon_trader.config import DEFAULT_CONFIG, REPO_ROOT, load_settings
from horizon_trader.data.store import load_bars
from horizon_trader.execution.costs import ZERO_COSTS, ibkr_costs
from horizon_trader.sleeves.alpha import AlphaSleeve
from horizon_trader.sleeves.static import StaticSleeve

DEFAULT_UNIVERSE = REPO_ROOT / "config" / "universes" / "us_large_cap.yaml"
ALPHA_DIR = REPO_ROOT / "research" / "alphas"
BENCHMARK = "equal-weight universe (no costs)"


def load_universe(path: Path) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return list(yaml.safe_load(f)["symbols"])


def _window(args: argparse.Namespace) -> slice:
    cutoff = pd.Timestamp(args.holdout_start)
    if args.holdout:
        return slice(cutoff, None)
    return slice(pd.Timestamp(args.start), cutoff - pd.Timedelta(days=1))


def _period_banner(args: argparse.Namespace, n_symbols: int) -> str:
    if args.holdout:
        return f"HOLDOUT {args.holdout_start}+ | {n_symbols} stocks"
    return (
        f"research period {args.start} to {args.holdout_start} (holdout hidden) | "
        f"{n_symbols} stocks"
    )


def cmd_extract(args: argparse.Namespace) -> None:
    from horizon_trader.alphas.extract import extract

    library, raw = extract(args.source, args.model)
    slug = re.sub(r"[^A-Za-z0-9.]+", "_", Path(args.source).stem or "paper").strip("_")
    out = Path(args.out or ALPHA_DIR / f"{slug}.yaml")
    save_library(library, out)
    out.with_suffix(".raw.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")

    print(f"{library.source}\n\n{library.notes}\n")
    print(f"{len(library.alphas)} testable alphas -> {out}")
    for a in library.alphas:
        print(f"  {a.name:<24} {a.formula}")
    if library.unsupported:
        print(f"\n{len(library.unsupported)} not testable with our data:")
        for u in library.unsupported:
            print(f"  {u.name:<24} needs {u.missing_data}")


def _format_ic_table(table: pd.DataFrame) -> str:
    out = table.copy().astype(object)
    for col in table.columns:
        if col.startswith("IC ") and "%" not in col:
            out[col] = table[col].map("{:+.4f}".format)
        elif col.startswith("t("):
            out[col] = table[col].map("{:+.2f}".format)
        else:
            out[col] = table[col].map("{:.1%}".format)
    return out.to_string()


def cmd_evaluate(args: argparse.Namespace) -> None:
    symbols = load_universe(args.universe)
    bars = load_bars(symbols)
    libraries = [load_library(p) for p in args.libraries]
    merged = AlphaLibrary(
        source="; ".join(lib.source for lib in libraries),
        alphas=[a for lib in libraries for a in lib.alphas],
    )
    table = evaluate_library(
        merged, bars, args.start, args.holdout_start, args.horizon, args.holdout
    )
    table = table.sort_values(f"t({args.horizon}d)", ascending=False)

    print(_period_banner(args, bars["close"].shape[1]))
    print("direction applied: positive IC = works the way the source claims\n")
    print(_format_ic_table(table))
    n = len(table)
    print(
        f"\n{n} variants tested: by chance alone expect ~{n * 0.05:.1f} with |t| > 2. "
        "Prefer signals with a stable sign in both halves over the single best t-stat."
    )


def cmd_backtest(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    symbols = load_universe(args.universe)
    bars = load_bars(symbols)
    spec = next((a for a in load_library(args.library).alphas if a.name == args.alpha), None)
    if spec is None:
        raise SystemExit(f"no alpha named {args.alpha!r} in {args.library}")
    params, _ = spec.variants()[0]

    window = _window(args)
    closes = bars["close"]
    runs = {}
    for rebalance in ("monthly", "weekly"):
        for top_n in (3, 5, 10):
            sleeve = AlphaSleeve(
                spec.name,
                spec.formula,
                spec.direction,
                params,
                top_n=top_n,
                rebalance=rebalance,
                bars_loader=lambda _syms: bars,
            )
            runs[f"top {top_n}, {rebalance}"] = sleeve.weights_history(closes)
    equal = {s: 1 / closes.shape[1] for s in closes.columns}
    # Frictionless: at $5k you'd hold this via an equal-weight ETF, not 100 tiny orders.
    runs[BENCHMARK] = StaticSleeve("ew", equal).weights_history(closes)

    costs = ibkr_costs(settings.costs.plan, settings.costs.slippage_bps)
    rows = {}
    for label, targets in runs.items():
        result = simulate(
            targets.loc[window],
            bars["open"].loc[window],
            closes.loc[window],
            settings.account.starting_cash,
            settings.execution,
            ZERO_COSTS if label == BENCHMARK else costs,
        )
        rows[label] = summarize(result.equity, result.trades)

    print(f"{spec.label(params)}: {spec.formula}  (direction {spec.direction:+d})")
    print(_period_banner(args, closes.shape[1]))
    print(f"${settings.account.starting_cash:,.0f} start, IBKR {settings.costs.plan} pricing\n")
    print(format_report(pd.DataFrame(rows).T))
    print(
        "\nBeat the equal-weight row, not SPY: it shares this list's survivorship bias. "
        "With a small account, commissions on many names can eat a real edge."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    ext = sub.add_parser("extract", help="turn a paper PDF (path or URL) into an alpha library")
    ext.add_argument("source")
    ext.add_argument("--out", type=Path)
    ext.add_argument("--model", default="claude-opus-5")
    ext.set_defaults(func=cmd_extract)

    def data_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
        p.add_argument("--start", default="2010-01-01")
        p.add_argument("--holdout-start", default="2024-01-01")
        p.add_argument("--holdout", action="store_true", help="report on the holdout period")

    ev = sub.add_parser("evaluate", help="IC report for one or more alpha libraries")
    ev.add_argument("libraries", nargs="+", type=Path)
    ev.add_argument("--horizon", type=int, default=5, help="forward-return days for t-stat")
    data_args(ev)
    ev.set_defaults(func=cmd_evaluate)

    bt = sub.add_parser("backtest", help="trade one alpha as a top-N long-only sleeve")
    bt.add_argument("library", type=Path)
    bt.add_argument("alpha")
    bt.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    data_args(bt)
    bt.set_defaults(func=cmd_backtest)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
