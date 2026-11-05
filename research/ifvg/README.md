# IFVG findings: no usable edge in this experiment

The mechanical IFVG rules failed on both SPY and QQQ. All **12** IFVG
instrument/entry/target combinations lost money over the full sample after
Tiered fees and one cent per share of slippage each side. All 12 also lost
under the three-cent stress case. The two entry styles at the primary 2R target
lost in both the 2021–23 and 2024–26 chronological periods.

These are results for the rules defined in [protocol.md](protocol.md), not a
claim that every discretionary IFVG interpretation or futures implementation
must fail. The experiment uses 1,248 complete common sessions from October 4,
2021 through September 24, 2026, with one incomplete date excluded.

## Primary 2R results

Each row is a separate $5,000 account, with whole shares, a 1% planned risk cap,
at most 1x exposure and one trade per day. Annualized returns are CAGR.

| Instrument | Entry | Trades | Gross CAGR | Net CAGR | Net max drawdown | Net profit factor |
| --- | --- | --- | --- | --- | --- | --- |
| SPY | Inversion close | 1,001 | +0.61% | -3.73% | -18.38% | 0.77 |
| SPY | Confirmed retest | 595 | -0.22% | -2.81% | -13.33% | 0.73 |
| QQQ | Inversion close | 1,038 | +0.89% | -3.97% | -18.25% | 0.82 |
| QQQ | Confirmed retest | 624 | -0.29% | -3.21% | -15.23% | 0.79 |

Gross and net accounts compound separately. To isolate the dollar cost drag,
the following calculation uses the exact quantities in the **net** accounts:

| Instrument / entry | Gross P&L on net positions | Fees | Slippage | Net P&L |
| --- | --- | --- | --- | --- |
| SPY / close | $160.47 | $848.03 | $174.54 | -$862.10 |
| QQQ / close | $190.42 | $888.09 | $214.86 | -$912.53 |

That is about $0.16–$0.18 of gross profit per trade against $1.02–$1.06 of
modeled costs. Both retest versions already lose before costs at 2R.

## Controls and uncertainty

The QQQ close-through-range control earns 2.33% annualized net with a 0.28
zero-hurdle Sharpe. The other full-period 2R controls lose. This does not establish
the control as an attractive strategy; its returns are small, its stops differ,
and it was evaluated alongside other configurations on reused history.

All four IFVG 2R/net mean daily return estimates have negative descriptive 95%
block-bootstrap intervals. However, each paired IFVG-minus-control interval
includes zero. Thus these results support rejecting these IFVG rules for this
account/cost model, rather than claiming statistically established superiority
of one trigger. Intervals are unadjusted for multiple comparisons.

The 2R stop-first ambiguity counts are 8/1,001 and 6/595 on SPY, and 14/1,038
and 1/624 on QQQ, for close and retest entries respectively. Signals and fills
use completed candles and subsequent minute opens; there is no same-candle
retroactive entry. Minute bars still cannot identify exact intraminute ordering.

## Saved evidence

- [Full report and controls](report.md)
- [Every configuration](metrics.csv), [bootstrap intervals](uncertainty.csv)
- [Standalone interactive chart](../../data/ifvg_2026_10_18/equity.html)
- [Verification](verification.json): 51 tests passed; all 216 account paths
  reconcile; 64 real trades passed causal signal and independent exit replay.
- [Audit source](verify.py), [recorded test results](verification.xml)

Reproduce the test record with:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_ifvg.py \
  tests/test_results_catalog.py tests/test_backtest.py tests/test_research_stats.py \
  -q -p no:cacheprovider --junitxml=research/ifvg/verification.xml
python research/ifvg/verify.py
```

The plugin-autoload setting isolates pytest from this machine's unrelated ROS
plugins. The experiment is registered in the dashboard Results catalog. No
parameters were retuned after observing performance, and no trading executor
or live configuration was changed.
