# What ORB stops and EMA exits actually do

**The existing ORB remains a credible research candidate under the requested cost
assumptions. The exit experiments show that reducing stop-outs alone is not a
sufficient objective.** EMA exits avoid losses on some trades but surrender larger
gains on others. This is a diagnosis of the tested rules, not proof that further
optimization will succeed or that the historical edge will persist.

Same **1,001 original ORB entries**, 2021-10-22 to 2026-10-01; one selected stock
per day, 1 prior daily ATR stop, 12-period EMA, Tiered plus assumed **1c per share
on entry and non-auction exits**. There are 1,240 sessions, including 239 without
an entry. Long and short trades are measured in their original trade direction.
One R is the original stop distance per share, or shares times that distance in
dollars. All rates below describe this historical sample.

## How trades exit

Denominator: **all 1,001 triggered trades** in each row.

| Exit rule | Hit fixed stop | EMA exit | Close auction | Profitable after modeled costs |
| --- | ---: | ---: | ---: | ---: |
| Original ORB | 315 / **31.5%** | 0 / 0% | 686 / 68.5% | **45.0%** |
| 5-minute EMA exit | 127 / **12.7%** | 864 / 86.3% | 10 / 1.0% | **39.1%** |
| 15-minute EMA exit | 177 / **17.7%** | 654 / 65.3% | 170 / 17.0% | **41.7%** |

Not hitting the stop does not mean winning: some positions close at a smaller
loss. The ordinary ORB wins fewer than half its trades but its average gross
winner is **+1.07R**, versus **-0.72R** for its average loser. Its mean gross
result is **+0.115R** per trade, and mean net result **+0.086R**, using its own
modeled position sizes. Gross profit factor, summing R gains/losses, is **1.30**;
net dollar profit factor on the simulated portfolio is **1.20**.

The 15-minute variant's average gross winner falls to **+0.78R**, its loser to
**-0.52R**, and its mean gross result to **+0.063R**. Net dollar profit factor is
**1.07**. It shrinks both sides of the distribution, with the net effect seen in
the earlier **4.42% versus 16.82%** CAGR comparison.

## When the stop is hit

Denominator for the percentages in this table: **stop-outs**, not all trades.
Timing is from the entry bar to the stopping bar, with roughly one-minute
resolution. Stops stay active between EMA decision times.

| Elapsed since entry | Original ORB: 315 stops | 15-minute EMA: 177 stops |
| --- | ---: | ---: |
| Under 5 minutes | 42 / 13.3% | 42 / 23.7% |
| 5 to under 15 minutes | 63 / 20.0% | 50 / 28.2% |
| 15 to under 30 minutes | 47 / 14.9% | 30 / 16.9% |
| 30 to under 60 minutes | 39 / 12.4% | 21 / 11.9% |
| 60 to under 120 minutes | 50 / 15.9% | 19 / 10.7% |
| 120 minutes or later | 74 / 23.5% | 15 / 8.5% |

- **Original ORB:** median stop time is **32 minutes after entry**; 48.3% of
  stop-outs occur within 30 minutes and 60.6% within an hour. In terms of all
  trades, those are **15.2%** and **19.1%**, respectively.
- **15-minute EMA:** median stop time is **13 minutes**; 68.9% of its stop-outs
  occur within 30 minutes and 80.8% within an hour. Its EMA exits remove some
  positions that would otherwise stop out later, which changes this conditional
  distribution; it does not move the hard stop closer.
- Fourteen stops occur in the entry minute: **1.4% of all trades**. The inherited
  conservative minute-bar model counts any same-minute stop touch. Precise
  within-minute ordering is unresolved for intraminute entries.

Clock time, **New York / ET**, for the original ORB:

| Stop time | Count | Share of the 315 stops |
| --- | ---: | ---: |
| Before 10:00 | 125 | 39.7% |
| 10:00-10:30 | 49 | 15.6% |
| 10:30-11:00 | 25 | 7.9% |
| 11:00-12:00 | 43 | 13.7% |
| 12:00-14:00 | 34 | 10.8% |
| 14:00-close | 39 | 12.4% |

**55.2%** of original stop-outs occur before 10:30, versus **75.7%** of the
15-minute variant's stops. These counts alone do not justify delaying entries:
most entries also occur early. [Timing data](stop_timing.csv) includes trades
still open at each elapsed-time interval's start. For example, the original
ORB's first five minutes stop out 42/1,001 positions, **4.2%**; its 5-15 minute
interval stops 63/958 survivors, **6.6%**. Interval lengths differ, so these are
interval risks, not comparable per-minute hazard estimates.

## How often does price keep going after an EMA exit?

Denominator: **EMA exits only** — 864 at five minutes and 654 at fifteen minutes.
The baseline counterfactual preserves the original stop and otherwise closes at
the official auction. Both alternatives use the same share count for each trade:
the baseline portfolio's quantity that day. Net comparisons include Tiered costs
and the requested 1c slippage, with no compounding-size mismatch.

| What happens after exit | 5-minute exits | 15-minute exits |
| --- | ---: | ---: |
| Any later favorable price, however small, ignoring a subsequent stop | 855 / 99.0% | 649 / 99.2% |
| Later makes a new favorable extreme beyond the pre-exit peak, ignoring stop | 484 / 56.0% | 303 / 46.3% |
| New favorable extreme **before the original stop** | 462 / 53.5% | 288 / **44.0%** |
| Moves another **0.25R before the original stop** | 568 / 65.7% | 381 / 58.3% |
| Moves another **0.5R before the original stop** | 385 / 44.6% | 246 / **37.6%** |
| Moves another **1R before the original stop** | 180 / 20.8% | 111 / **17.0%** |
| Retaining original stop / closing later finishes better, after costs | 432 / **50.0%** | 326 / **49.8%** |
| EMA exit finishes better, after costs | 428 / 49.5% | 322 / **49.2%** |
| Same final net result | 4 / 0.5% | 6 / 0.9% |
| Original stop would later be hit | 188 / 21.8% | 138 / **21.1%** |

The near-99% figure mostly counts tiny bounces; it is a poor objective for exit
design. The material continuation rates and final stop-aware outcomes are more
useful. Ignoring subsequent stop hits, another 0.5R appears after **40.5%** of
15-minute EMA exits; requiring it before that stop reduces the figure to **37.6%**.
An excursion is not an executable strategy for capturing its maximum.

For the 15-minute rule, the 326 cases where holding wins contribute **211.94R**
of aggregate improvement, or **0.65R per case**. The 322 cases where exiting wins
save **156.34R**, or **0.49R per case**. Counts are nearly balanced, but holding
gains more when it wins. Across the 654 EMA exits this is **0.085R per exit** in
favor of holding; across all 1,001 trades, **0.0555R**. These are sums/means of
normalized paired outcomes, not compounded portfolio returns.

Only **278/654 = 42.5%** of the 15-minute EMA exits realize a positive net result
at matched quantities. A reversal exit is not inherently a take-profit exit.

The intraminute-ordering check computes lower/upper bounds for continuations
inside a stopping minute. At the stated 0.25R, 0.5R and 1R thresholds, the bounds
give identical counts in this sample. A gap stop cannot claim a later high/low
from the same minute. See [all continuation counts](continuation_summary.csv).

## What happens after the original stop-out?

Among the **315 original stop-outs**:

- **125 / 39.7%** later revisit the entry price or better, excluding the stopping
  minute's unknown later range. This ignores the already-executed stop.
- Only **56 / 17.8%** close the day beyond the entry in the original direction,
  before costs. A temporary rebound is not the same as a profitable close.
- **97 / 30.8%** had reached at least +0.5R in an earlier minute before stopping;
  **34 / 10.8%** had reached at least +1R. This describes giveback, but does not
  justify a breakeven stop without also measuring how often it cuts later winners.
- Hypothetically ignoring the stop, the median closing outcome of these stopped
  trades is **-0.97R**, and the worst is **-17.40R**. These are gross closing marks,
  not a simulated no-stop portfolio. The stop protects against some severe moves.

[Recovery summary](stop_recovery.json). This is not a recommendation to remove
the protective stop or automatically reenter after a rebound.

## How strong is the evidence?

The original ORB's stop rate is similar across reused periods: **31.9%** in
2021-23 and **31.1%** in 2024 onward. Mean net R is positive in both periods
(**+0.064R**, **+0.105R**) and for both longs and shorts (**+0.070R**, **+0.100R**).
These are descriptive results under the same fill assumptions; historical short
availability and borrow charges remain unmodeled.

The biggest **51 trades**, approximately the top 5%, generate **41.2% of all
positive gross R**. Their combined +204.73R exceeds the +114.82R total after
losses: the remaining trades sum to -89.91R. This is hindsight concentration,
not a method of selecting winners, but it shows why cutting strong moves is
expensive for this strategy.

Paired circular block bootstrap: 2,000 samples of 21 trading sessions, with the
flat sessions retained. Approximate 95% intervals:

| Statistic | Estimate | 95% interval |
| --- | ---: | ---: |
| Original stop-out rate | 31.5% | 28.7%-34.2% |
| 15-minute stop-out rate | 17.7% | 15.4%-20.0% |
| Holding better after a 15-minute EMA exit | 49.8% | 46.7%-53.1% |
| Another 0.5R before stop after a 15-minute EMA exit | 37.6% | 33.9%-41.2% |
| Original mean net R | +0.086R | +0.009R to +0.168R |
| 15-minute exit minus original, paired net R per trade | -0.0555R | -0.0964R to -0.0161R |

The paired net-R analysis uses identical shares in both alternatives. The
intervals condition on this sample and model, allow short-range dependence, and
do **not** account for earlier strategy selection or establish live profitability.
They are not a multiple-testing-adjusted claim that ORB has been proven.

## What this suggests testing next

The objective should be **more net expectancy while preserving large winners**,
with drawdown assessed alongside return. Stop-out rate or the number of exits
followed by any bounce is not sufficient. Nor does the early-stop concentration
establish that later entries improve the tradeoff.

One bounded next exit hypothesis is **two consecutive completed 15-minute closes
on the adverse side of the 12 EMA**, with the same always-active 1-ATR stop.
The proposed mechanism is fewer exits on single-candle pullbacks. It may also
exit true reversals later; this is a testable tradeoff, not an expected improvement.
It has **not** been implemented or tested here. Compare saved-loss R, surrendered
winner R, net expectancy and tail participation against the frozen control.

Entry quality and execution remain separate research questions. Higher relative
volume and entry cutoffs already appeared in the
[480-configuration study](../../orb_parameter_grid.md), where the configuration
chosen on 2021-23 underperformed the baseline in the later period in all eight
cost/account scenarios. Repeating optimization on seen data can fit noise;
[Bailey et al., *The Probability of Backtest Overfitting*](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
explains this selection problem. A new rule needs frozen settings and new
forward observations or additional history, rather than treating reused 2024+
data as untouched validation.

## Artifacts and checks

[Exit summary](exit_summary.csv), [stop timing](stop_timing.csv),
[continuation](continuation_summary.csv), [period/direction splits](subgroups.csv),
[uncertainty](uncertainty.csv), [verification](verification.json),
[definitions](protocol.md).
Offline interactive charts: `data/orb_ema_2026_10_02/exit_diagnostics.html`.
Private per-trade continuation and stop-recovery tables are in the same data
directory. The new diagnostic functions have eight focused tests; **56 targeted
tests pass** in total, and Ruff passes. Existing strategy rules/results were not
changed and no orders were sent.

```powershell
.venv/Scripts/python.exe research/orb_ema_2026_10_02/exit_diagnostics/analyze.py
.venv/Scripts/python.exe -m pytest tests/test_orb_exit_diagnostics.py tests/test_orb_ema.py tests/test_orb.py tests/test_ema_vwap.py -q -p no:cacheprovider --basetemp data/tmp/orb_exit_diagnostics_tests
```
