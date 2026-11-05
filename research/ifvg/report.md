# IFVG strategy backtest

**Result: all 12 IFVG configurations lost after costs over the full period.**
Read the [findings and cost breakdown](findings.md) and [verification](verification.json).

Data: 2021-10-04–2026-09-24, 1,248 common complete
sessions; 1 excluded date (1 instrument/date
issue). SPY and QQQ are tested as **separate $5,000 accounts**. These results
do not represent a combined portfolio or an NQ/ES futures test.

Rules were written in [protocol.md](protocol.md) before the first performance
run. Five-minute gap inversions, long and short, maximum one trade a day, entries
through 11:30 ET; stop beyond the zone, primary 2R target, flat before close.
Entry is at the next minute open after a completed signal. The retest variant
requires a later completed rejection candle. Position size includes stop
slippage and fees, risks at most 1% before stop gaps, and uses at most 1x capital.

## Primary results: Tiered fees and one cent per share each side

| ticker | strategy | period | trades | cagr | sharpe | max_drawdown | avg_pnl | profit_factor |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SPY | ifvg_close | all | 1001 | -3.7% | -1.42 | -18.4% | -0.86 | 0.77 |
| SPY | ifvg_close | 2021-23 | 448 | -2.3% | -0.74 | -7.1% | -0.58 | 0.87 |
| SPY | ifvg_close | 2024+ | 553 | -4.8% | -2.29 | -12.9% | -1.13 | 0.67 |
| SPY | ifvg_retest | all | 595 | -2.8% | -1.31 | -13.3% | -1.11 | 0.73 |
| SPY | ifvg_retest | 2021-23 | 268 | -2.9% | -1.11 | -6.7% | -1.17 | 0.77 |
| SPY | ifvg_retest | 2024+ | 327 | -2.6% | -1.47 | -8.0% | -1.08 | 0.71 |
| SPY | breakout_close | all | 1248 | -6.1% | -0.87 | -28.4% | -1.08 | 0.87 |
| SPY | breakout_close | 2021-23 | 563 | -7.6% | -0.91 | -20.4% | -1.45 | 0.86 |
| SPY | breakout_close | 2024+ | 685 | -4.0% | -0.67 | -13.1% | -0.77 | 0.90 |
| SPY | breakout_retest | all | 1100 | -3.9% | -0.62 | -22.6% | -0.83 | 0.90 |
| SPY | breakout_retest | 2021-23 | 493 | -3.7% | -0.47 | -15.8% | -0.81 | 0.92 |
| SPY | breakout_retest | 2024+ | 607 | -4.0% | -0.77 | -13.9% | -0.87 | 0.88 |
| QQQ | ifvg_close | all | 1038 | -4.0% | -1.08 | -18.3% | -0.88 | 0.82 |
| QQQ | ifvg_close | 2021-23 | 476 | -3.0% | -0.65 | -11.8% | -0.68 | 0.88 |
| QQQ | ifvg_close | 2024+ | 562 | -4.7% | -1.58 | -12.3% | -1.10 | 0.75 |
| QQQ | ifvg_retest | all | 624 | -3.2% | -1.01 | -15.2% | -1.20 | 0.79 |
| QQQ | ifvg_retest | 2021-23 | 281 | -3.2% | -0.82 | -7.1% | -1.25 | 0.82 |
| QQQ | ifvg_retest | 2024+ | 343 | -2.9% | -1.18 | -8.2% | -1.13 | 0.77 |
| QQQ | breakout_close | all | 1248 | 2.3% | 0.28 | -13.0% | 0.49 | 1.03 |
| QQQ | breakout_close | 2021-23 | 563 | 3.2% | 0.33 | -13.0% | 0.65 | 1.04 |
| QQQ | breakout_close | 2024+ | 685 | 0.9% | 0.15 | -12.1% | 0.18 | 1.02 |
| QQQ | breakout_retest | all | 1076 | -1.8% | -0.17 | -14.4% | -0.40 | 0.97 |
| QQQ | breakout_retest | 2021-23 | 481 | -3.5% | -0.30 | -14.4% | -0.79 | 0.94 |
| QQQ | breakout_retest | 2024+ | 595 | 0.2% | 0.07 | -7.2% | 0.05 | 1.00 |

Of the four IFVG instrument/entry combinations, **0 were
profitable in both chronological periods** at the primary 2R/net assumptions.
This is a descriptive screen, not a significance test or a recommendation.
The 2024+ period and the earlier period each restart at $5,000. History has
already been reused by other strategies; neither is a pristine holdout.

## Evidence and reproducibility

- [All 216 configuration/period/cost rows](metrics.csv): gross, Tiered/1c,
  Tiered/3c; 1R, 2R, 3R; all four triggers and both ETFs.
- [Primary equity paths](equity.csv), [yearly returns](annual_returns.csv),
  [long/short and exit breakdown](trade_breakdown.csv).
- [Block-bootstrap intervals](uncertainty.csv): 20-session blocks, 2,000 draws.
  Mean daily returns and paired differences versus the corresponding breakout
  control. Unadjusted descriptive 95% intervals; not independent-trade tests.
- [Data exclusions](skipped_sessions.csv), [source/data hashes](manifest.json).
- Full trade paths, all sized fills, daily account paths and a standalone
  interactive equity/drawdown chart are registered in this study's Results entry
  under `data/ifvg_2026_10_18/`. The report CSVs contain derived results, not raw bars.

Run from the repository root:

```bash
python -m horizon_trader.intraday.ifvg_study
pytest tests/test_ifvg.py
```

The runner reads only existing caches and refuses to fetch data. The original
run used an isolated Linux environment at `/tmp/horizon-ifvg-venv`, installed
from the repository lockfile. Temporary environments need recreation after cleanup.

## Interpretation and limitations

The breakout controls use the same timing and account rules but different event
times and stop widths. They benchmark an alternative trigger; their difference
does not causally isolate IFVG. Parameters were not optimized, and all 24
instrument/strategy/target configurations are reported.

Minute-bar exits use stop-first treatment when both barriers are touched;
`ambiguous` counts these cases. Stops gapped through fill at the worse open.
Targets get no favorable gap improvement and pay the same slippage allowance.
Slippage is assumed, not measured from quotes. The report includes gross P&L
on the exact net positions as well as separately compounded zero-cost accounts.

Sharpe uses a zero cash hurdle, with no cash interest. The fixed repository fee
schedule is applied across history. Borrow/locates, short-sale restrictions,
taxes, subscriptions, broker margin and settlement are not modeled. Strict
complete-session screening removes some days retrospectively; exclusions are
explicit and identical across configurations. Session ends use the existing
SPY-coverage proxy. One trade is selected per day before sizing; zero-share
trades are skipped without searching for a replacement.

These are historical simulations. A favorable row would still need genuinely
new forward observations and execution checks before being treated as an edge.
