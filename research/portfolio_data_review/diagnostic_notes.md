# Portfolio complementarity diagnostic — 2026-10-01

The existing intraday sleeves are complementary to the daily core in this
history. That supports a shared-account replay as the next research experiment;
it does not establish that a tradeable combination has Sharpe above one.

## Reproduction and scope

```powershell
.venv\Scripts\python.exe research/portfolio_data_review/analyze_portfolio.py
```

The script reads local caches and saved bundles directly. It makes no network
requests, refreshes no caches, and changes no strategy parameters, existing
research, live settings, or orders. Outputs include the full return panel,
metrics, fills, source hashes, frozen training weights, conditional correlations,
bootstrap intervals, and an offline [interactive correlation heatmap](correlation_heatmap.html).
The same standalone HTML also contains an exportable
[equity and drawdown figure](correlation_heatmap.html#equity-drawdown); its dashed
blend curves are explicitly marked screening arithmetic. Matplotlib is absent,
so Plotly supplies the figure and its browser PNG-download button; only one
offline Plotly library is embedded. Numerical plotted curves are saved as
`results/plotted_equity.csv` and `results/plotted_drawdown.csv`.

`results/effective_daily_settings.json` freezes the effective research settings
(Fixed pricing, no live settings or credentials). Future runs load this snapshot
by default. The manifest records effective/source config hashes and hashes of
the analysis and reused implementation files. `results/experiment_ledger.csv`
lists every standalone, sensitivity, synthetic blend, delete-one control and
historical reconciliation, including failure/limitation decisions; synthetic
blends receive no objective-acceptance designation.

Primary dates are **2021-11-02 through 2026-09-24**, with starting NAV on
2021-11-01. Each primary sleeve starts with $5,000 and **Fixed** commissions.
The daily core and standalone 756-session risk parity reuse existing daily
simulations and adjusted data. The QQQ noise rule is reconstructed from cached
QQQ minute/day bars with its existing 2% daily volatility target, 4x cap, and
$0.005/share slippage on non-closing-auction fills. ORB replays the saved baseline
top-one, one-ATR, measured stop-limit fill outcomes with 1% account risk per trade.
Replaying the original ORB bundle with its full original calendar reproduces
every NAV exactly (maximum dollar difference **0.0**). The new primary ORB starts
on the shared date; no tuned relative-volume/cutoff candidate is used.

All source histories have already appeared in repository research. The later
period is a **reused historical test**, not untouched evidence. Winners is
supplementary because it starts only on 2022-11-01, uses Tiered costs, fractional
shares and price-only returns, and therefore cannot be mixed into the primary
2021-start Fixed-cost comparisons as though equivalent.

## Cash and performance conventions

Source returns include modeled commissions/slippage but earn zero on idle cash.
An intraday sleeve is a daily trading payoff on its reference account, not a
payoff plus a separate Treasury yield. Every constructed portfolio uses
`portfolio_return = sum(weight * source_return)`, then subtracts **one** shared
lagged DFF ACT/360 calendar accrual to calculate excess returns. We neither add
cash interest per intraday sleeve nor subtract the cash benchmark multiple times.
Sharpe is mean daily excess return / sample standard deviation times sqrt(252).
Excess Sortino is mean daily excess return divided by the square root of the
mean squared negative excess return over **all** sessions, times sqrt(252).
Zero-rate Sharpe is also saved to reconcile old reports. CAGR uses actual elapsed
calendar years; close-to-close drawdowns include starting NAV.

The equal-risk screen estimates inverse standalone volatility on **2021–2023**,
normalizes weights to one, and freezes them for 2024 onward: daily core **51.60%**,
ORB **20.33%**, QQQ noise **28.07%**. Its full-period result includes the weight
estimation sample. This is inverse standalone volatility, not an optimizer or
exact covariance risk parity. Three delete-one diagnostics leave the deleted
weight in zero-yield cash instead of silently renormalizing the surviving weights.

All return combinations are **screening arithmetic**. Scaling a net return
stream scales its already-paid commissions and changes its reference account
size; actual minimum fees, rounding, financing, overlapping orders, and margin
will not generally scale that way. No synthetic portfolio curve is presented as
an executable account backtest.

## Main evidence

| Fixed-cost modeled stream/screen | Full excess Sharpe | 2024+ excess Sharpe | Full CAGR | Full maximum DD |
|---|---:|---:|---:|---:|
| Daily core | 0.32 | 0.79 | 6.35% | -10.42% |
| ORB baseline | 0.31 | 0.47 | 8.24% | -22.99% |
| QQQ noise | 0.82 | 0.64 | 15.13% | -17.11% |
| Risk parity standalone | 0.31 | 1.02 | 6.50% | -18.14% |
| Frozen inverse-volatility screen | 0.83 | 1.12 | 9.72% | -5.02% |
| Daily + QQQ noise return sum | 1.14 | 1.25 | 22.51% | -10.64% |
| Daily + 0.25 ORB + 0.5 QQQ noise screen | 1.09 | 1.40 | 17.02% | -8.92% |
| Same reduced screen, additional slippage | 0.96 | 1.29 | 15.38% | -9.11% |

The reduced screen's weights are fixed illustrative scales, not searched for a
maximum Sharpe. Its nominal worst-case sleeve limits add to 4x (daily 1x + 0.25
times ORB 4x + 0.5 times noise 4x). This arithmetic does not establish available
broker buying power or intraday margin compliance. The additional slippage case
adds one cent per share to **both** ORB fills and increases QQQ noise slippage
from half a cent to one cent on its modeled non-auction fills. It does not test
missed limit fills, borrow availability, closing-auction spread, or market impact.

Daily core correlation with ORB is **+0.051** overall and **+0.060** after 2024;
with QQQ noise it is **-0.048** and **-0.059**. In 2022 those pairs are +0.020
and +0.025. On sessions when QQQ is more than 10% below its running peak they
are +0.051 and +0.127. Low ordinary correlation therefore broadly persists in
the available stress periods, but tail dependence remains imprecise. Conditional
statistics are descriptive and cannot be treated as trading signals.

Risk parity is much less independent: correlation with the daily core is **0.74**
overall and **0.87** after 2024. The supplementary winners stream correlates
**0.70** with the daily core and **0.71** with QQQ on its shorter sample. It adds
less diversification to existing equity exposure and retains major practical
whole-share/account-concentration caveats from the repository.

## Uncertainty and the previous 1.69 claim

The saved Tiered daily-core and QQQ-noise streams reproduce the old **1.690691**
zero-rate Sharpe exactly when added. Subtracting one cash hurdle reduces it to
**1.439242**. Fixed-cost replays reduce the corresponding figure to **1.137518**.
Thus the published arithmetic is reproducible; its implementation as one funded,
margin-constrained account remains unverified. QQQ noise can independently reach
4x, so simply overlaying the daily book exceeds its nominal gross limit on some
days. The previous overlay was devised after inspecting the underlying results.

Paired circular block bootstrap diagnostics use 1,000 samples of 21-session
blocks, seed 20261001. For the reused 2024+ sample:

- The equal-risk screen's excess Sharpe 1.12 has a 95% interval **0.18–1.99**.
- The daily-plus-noise screen's improvement over the core is +0.47 Sharpe units,
  interval **-0.78 to +1.51**.
- The reduced screen's improvement is +0.62, interval **-0.28 to +1.34**.

Intervals are conditional on the observed return streams, preserve paired dates,
and do not account for prior repository searches, selection of QQQ after SPY,
execution-model error, or testing nine reported portfolio constructions including
three delete-one diagnostics. None establishes a durable Sharpe greater than one.
The frozen screen's 2024+ excess Sharpe falls from 1.12 to 0.90 without ORB,
0.68 without noise, and 0.40 without the daily core; removed weights remain cash.

## Limits to preserve in the next experiment

Build a shared-account allocator and replay before a portfolio paper-trading
recommendation: one NAV, explicit overnight holdings, intraday order timestamps,
actual raw shares, Fixed minimum fees, netted executions, buying-power reservation,
shared short constraints, and simultaneous exposure. Re-estimate costs as account
equity evolves instead of summing independent account returns. Quantify missed
stop-limit fills and retry behavior, and validate QQQ MOC assumptions.

Current daily simulations retain synthetic adjusted-share accounting and
fractional-order assumptions. ORB retains selection/second-bar fill-model and
short-borrow/SSR limitations; the saved bundle does not recover unobserved bids,
asks, queues, or rejected orders. QQQ's cached minute simulator fills at the next
minute open, permits stale intraminute fallback, and does not charge exit slippage
on closing-auction orders. Each is a limitation of the inherited screen.

The best immediate use of this evidence is to prioritize the replay and collect
forward execution measurements, then test frozen choices on genuinely additional
history or future observations. No new data purchase was made for this diagnostic.
