# ORB: two-close EMA exits, 0.5-ATR stops and larger positions

The narrower stop makes surviving winners larger, but the extra stop-outs more
than offset that benefit in this sample. Two-close confirmation modestly improves
the 1-ATR EMA exit. It still trails the original ORB, and its drawdown is larger.
Increasing the risk budget magnifies both the favorable and unfavorable results.

Executed 2026-10-03 on the frozen **2021-10-22 through 2026-10-01** sample:
**1,001 identical original ORB entries across 1,240 sessions**. Starting equity
is $5,000, with whole shares, compounding, the existing IBKR Tiered cost model,
and **1c/share slippage on entries and non-auction exits**. Closing-auction exits
retain the previous official-close assumption. ATR means prior 14-day daily ATR.
All drawdowns below use daily closing equity; intraday drawdowns can be larger.

The new rule waits for **two consecutive completed 15-minute closes against
EMA(12)**, then exits at the next available minute open. Favorable/equal closes
and missing intervening candles reset the counter. The initial fixed stop stays
active. Entry selection and the five-minute opening range are unchanged.

## Results after modeled costs

All rows below have a **2x notional ceiling**. Risk is the planned stop-distance
loss as a percentage of current equity, before costs, gaps and whole-share rounding.
The stop rate has the same denominator of 1,001 trades in every row.

| Exit | Stop, daily ATR | Risk/trade | Annualized return | Maximum drawdown | Stop rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original ORB, stop or close | 1.0 | 1% | **+16.82%** | 21.11% | 31.47% |
| Original ORB, stop or close | 1.0 | 2% | +34.41% | 38.17% | 31.47% |
| Original ORB, stop or close | 0.5 | 1% | -2.66% | 49.15% | 56.24% |
| Original ORB, stop or close | 0.5 | 2% | -9.66% | 77.86% | 56.24% |
| One adverse 15-minute EMA close | 1.0 | 1% | +4.42% | 19.71% | 17.68% |
| One adverse 15-minute EMA close | 1.0 | 2% | +9.36% | 35.27% | 17.68% |
| One adverse 15-minute EMA close | 0.5 | 1% | -11.16% | 56.37% | 40.16% |
| One adverse 15-minute EMA close | 0.5 | 2% | -23.51% | 81.87% | 40.16% |
| Two adverse 15-minute EMA closes | 1.0 | 1% | **+6.07%** | 23.27% | 21.38% |
| Two adverse 15-minute EMA closes | 1.0 | 2% | +12.81% | 41.00% | 21.38% |
| Two adverse 15-minute EMA closes | 0.5 | 1% | **-12.87%** | 58.62% | 46.15% |
| Two adverse 15-minute EMA closes | 0.5 | 2% | **-26.98%** | 85.30% | 46.15% |

For the two-close exit, $5,000 finishes at **$6,691** with 1 ATR/1% risk,
**$9,073** with 1 ATR/2% risk, **$2,529** with 0.5 ATR/1% risk and **$1,056**
with 0.5 ATR/2% risk. Original ORB at 1 ATR/1% risk finishes at **$10,786**.

There are **24 exit/stop/risk/cap configurations**, also evaluated before costs
and on two separate subperiods: [all 144 result rows](metrics.csv). Before costs,
the two-close version at 1% risk/2x cap returns +13.59% annually with 1 ATR,
versus -1.17% with 0.5 ATR. Costs worsen an already weak narrow-stop result.

## Why bigger winners do not rescue the tighter stop

At the same account equity and uncapped sizing, halving the price distance doubles
the shares for the same planned dollar loss. For example, with $5,000 equity and
a $1 daily ATR:

| Stop | Planned equity risk | Shares before cap/rounding | Gain for the same favorable $2 exit move |
| --- | ---: | ---: | ---: |
| $1 = 1 ATR | 1% = $50 | 50 | $100 |
| $0.50 = 0.5 ATR | 1% = $50 | 100 | $200 |
| $0.50 = 0.5 ATR | 2% = $100 | 200 | $400 |

These examples exclude costs. They assume the trade reaches that exit without
first touching its stop. A 0.5-ATR price stop is the new trade's **1R**, not half
the dollar risk when shares are increased to restore the original risk budget.

In the actual two-close simulation at 1% risk and a 2x cap:

| Statistic | 1 ATR | 0.5 ATR |
| --- | ---: | ---: |
| Average winning trade, net % of equity before that trade | +0.87% | **+1.52%** |
| Average losing trade, net % of equity before that trade | -0.57% | **-0.85%** |
| Net profitable trades | 422 / **42.16%** | 335 / **33.47%** |
| Fixed-stop exits | 214 / 21.38% | 462 / 46.15% |
| EMA exits | 553 / 55.24% | 366 / 36.56% |
| Closing-auction exits | 234 / 23.38% | 173 / 17.28% |

Using **identical share counts within each paired comparison**, **87 of the 422
wide-stop winners (20.62%)** become losses at the narrower stop. The remaining
335 wide-stop winners keep the same raw exit. In original ORB, the narrower stop
removes **116 of 450 winners (25.78%)**. These comparisons isolate the changed
trade path from different compounded account sizes and fee minima.

The two-close rule's narrow-stop path loses an average **0.0685 original 1-ATR R
per trade** relative to its wide-stop path at matched share counts. Increasing
the number of shares does not remove that lost price movement.
[Paired stop diagnostics](narrow_stop_pairs.csv).

## When the stops happen

Timing percentages below are conditional on a stop-out. Resolution is one minute;
entry-minute stops use the inherited conservative assumption about price ordering.

| Exit and stop | Number of stops | Median minutes after entry | Under 30 minutes | Under 60 minutes |
| --- | ---: | ---: | ---: | ---: |
| Original ORB, 1 ATR | 315 | 32 | 48.3% | 60.6% |
| Original ORB, 0.5 ATR | 563 | 10 | 67.7% | 77.3% |
| One EMA close, 1 ATR | 177 | 13 | 68.9% | 80.8% |
| One EMA close, 0.5 ATR | 402 | 5 | 81.3% | 87.8% |
| Two EMA closes, 1 ATR | 214 | **15.5** | 68.7% | 79.4% |
| Two EMA closes, 0.5 ATR | 462 | **6** | 80.5% | 87.9% |

At 0.5 ATR, many positions hit the fixed stop before a second adverse 15-minute
close is available. This limits what additional EMA confirmation can accomplish.
There are **94 entry-minute stops** with 0.5 ATR versus **14** with 1 ATR across
each exit variant, a material minute-bar limitation.

As a diagnostic added after seeing the results, 28 of the two-close version's
87 lost winners involve these entry-minute stops. Excluding all 94 affected
dates from both sides leaves 907 matched trades; the narrow path still loses
**0.0251 original R/trade** relative to the wide path. This is a path diagnostic,
not an executable filter or an optimistic fill simulation. Tick-level sequencing
would be needed to resolve the ambiguous entries. [Exit and timing counts](paths.csv).

## Did two-close confirmation fix premature exits?

At 1 ATR, the one-close version exits 654 trades on EMA and the two-close version
exits 553. On matched quantities, waiting for confirmation improves 300 trades,
worsens 347 and leaves 354 unchanged. The improved trades add **82.98R** while
the worsened trades lose **74.49R**, a net **+0.00848R per original entry**.
Waiting also produces **37 additional fixed-stop exits**.

A paired 21-session circular-block bootstrap, 2,000 resamples, gives a descriptive
95% interval of **-0.0103R to +0.0292R** for that mean improvement. It includes
zero; the modest gain does not establish a reliable improvement.
[Paired exit changes](confirmation_pairs.csv), [intervals](uncertainty.csv).

Of the **553 two-close EMA exits at 1 ATR**:

- **37.8%** subsequently move another 0.5R in the original direction before the
  original stop; **14.8%** move another 1R. These use conservative minute ordering.
- Keeping the original stop and otherwise holding to the close finishes better,
  after costs at matched quantities, **53.5%** of the time.
- The original stop would later be hit on **18.3%**.

These are conditional groups with different membership from the earlier 654-exit
sample. Confirmation delays some exits but does not recover the original ORB's
overall payoff distribution. [Continuation diagnostics](continuation.csv).

## What higher leverage changes

The notional cap is a ceiling, not a target. Shares are
`floor(min(equity * risk / stop_distance, equity * cap / entry_fill))`.
Increasing a nonbinding cap leaves the position unchanged.

For the two-close rule at a 2x cap, mean entry notional/equity is approximately:

| Stop | Risk budget | Mean entry exposure | Trades constrained by 2x cap |
| --- | ---: | ---: | ---: |
| 1 ATR | 1% | 0.24x | 0 / 1,001 |
| 1 ATR | 2% | 0.48x | 2 / 1,001 |
| 0.5 ATR | 1% | 0.48x | 2 / 1,001 |
| 0.5 ATR | 2% | 0.94x | 59 / 1,001 |

Moving the cap from 2x to 4x does **nothing** at 1 ATR/1% risk. At 0.5 ATR/2%
risk, the two-close result changes from **-26.98% CAGR / 85.30% drawdown** to
**-27.30% CAGR / 85.41% drawdown**. Mean exposure rises from 0.94x to 0.97x.
The higher ceiling does not create the intended larger profitable edge.

To meaningfully enlarge most trades in this model, the risk budget must rise.
At 1 ATR, doubling it raises the two-close CAGR from 6.07% to 12.81%, while
drawdown rises from 23.27% to 41.00%. Original ORB rises from 16.82% to 34.41%
with drawdown increasing from 21.11% to 38.17%. These are simulated sizing
tradeoffs, not evidence of account capacity or a recommendation to increase risk.

The worst realized trade in the two-close account loses **1.56%** at 1 ATR/1%
risk, **3.11%** at 1 ATR/2% risk, **1.69%** at 0.5 ATR/1% risk and **3.52%** at
0.5 ATR/2% risk. Fees, slippage and gaps can exceed the nominal stop budget.
The [SEC stop-order bulletin](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-15)
explains why a stop price does not guarantee the execution price.

## Consistency across time and limits

Each subperiod below restarts at $5,000, with 1% risk and a 2x cap. Neither
period is an untouched validation set: both have been examined in earlier work.

| Exit | Stop | 2021-23 CAGR | 2024 through 2026-10-01 CAGR |
| --- | ---: | ---: | ---: |
| Original ORB | 1 ATR | +12.50% | +19.94% |
| Original ORB | 0.5 ATR | +9.23% | -11.51% |
| One EMA close | 1 ATR | +3.01% | +5.20% |
| One EMA close | 0.5 ATR | +0.14% | -19.22% |
| Two EMA closes | 1 ATR | +4.08% | +7.63% |
| Two EMA closes | 0.5 ATR | -4.96% | -18.64% |

The 1-ATR ORB remains the benchmark for further research. This experiment does
not support adopting the 0.5-ATR stop, and the two-close exit is still weaker
than that benchmark. Future hypotheses need a genuinely new validation period;
repeatedly choosing better settings on these same dates cannot establish that
they will work out of sample.

The existing Tiered fee assumptions are held constant throughout the history;
this is not a reconstruction of each historical month's broker fee schedule.
Borrow availability/locate costs, size-dependent market impact, dynamic house
margin and forced liquidation are absent. The **2x and 4x caps are hypothetical**,
not verified buying power for this account. See
[IBKR's margin documentation](https://www.interactivebrokers.com/en/trading/margin-requirements.php)
for account and house-margin constraints. No broker orders or operational
settings were changed.

## Reproduction and verification

Run `.venv\Scripts\python.exe research/orb_ema_2026_10_02/confirmation_risk/run.py`
from the repository root. It reads only local frozen source/cache files.

- The original and one-close rules reproduce **4,004 saved trades exactly**
  across both stop widths, including entry/exit timestamps, prices and reasons.
- All six paths share the same 1,001 entries. **24 prior account result rows**
  reproduce within 1e-12; all 144 new account runs stay solvent and execute every
  eligible trade. P&L, risk budgets and notional caps reconcile.
- **66 targeted tests pass**, including long/short confirmation, resets, missing
  candles, pre-entry exclusion, stop priority and gaps, causal signal use, and
  risk-versus-cap sizing. Ruff checks pass.
- [Protocol](protocol.md), [runner](run.py), [hashes and verification](verification.json).
- Interactive comparison: `data/orb_ema_2026_10_02/confirmation_risk.html`.
  Private raw trades, fills, equity curves and paired diagnostics are stored
  alongside it as `confirmation_risk*.parquet`.
