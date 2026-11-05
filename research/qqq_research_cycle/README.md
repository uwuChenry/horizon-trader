# QQQ research cycle — 2026-10-01

**No candidate meets the objective.** Across 2007–2026-09-30, QQQ total return
compounds at 16.34% with a 53.40% maximum drawdown. All nine new candidate variants
reduce drawdown by more than the required 10% relative amount over the full period,
but all sacrifice return. None passes both targets in 2016–2020 validation or the
2021+ historical confirmation. The development-selected six-month rotation is
rejected: 11.12% net CAGR and 35.96% drawdown, versus QQQ's 16.34% and 53.40%.

The most informative control is **volatility-only QQQ**: 16.22% net CAGR and 38.70%
drawdown (27.5% smaller), a near match in growth, not a win. Its 2021+ period passes
both targets, but validation does not. Adding the trend gate lowers full-period
growth to 11.95%. Constant 1.25x QQQ raises CAGR to 19.03% while worsening drawdown
to 63.02%; that is leverage, not the requested improvement.

Recommendation: **reject the selected rotation for this objective; continue narrowly
scoped risk-sizing research. Do not promote a strategy to paper trading on this
cycle's performance evidence.** No orders or live-setting changes were made.

## Current system and data assessment

The repository combines close-time target-weight ETF sleeves (momentum, trend,
volatility management, mean reversion), portfolio caps, and next-open execution.
It also contains ORB, intraday momentum, point-in-time stock/fundamental research,
social and disclosure event studies, and broker/shadow infrastructure. Relevant
existing research was read; unrelated application code was not exhaustively audited.

The existing Tiered/5bp/$5k daily baseline reproduces for 2008-01-02–2026-09-30:
combined 6.4% CAGR / -11.5% DD, QQQ 16.4% / -49.4%. These legacy results use different
start dates and execution conventions from the new table and must not be mixed.
See [simulator audit](legacy_audit.md) and [data audit](data_audit.md).

Two defects were fixed with regression tests: the legacy simulator invented fills
at stale prior closes when opens were absent/invalid; its analytics Sortino used
conditional negative-return standard deviation instead of downside RMS. Complete
ETF-panel baseline results were unaffected by the missing-open fix. Remaining
legacy issues include adjusted-unit share fees, exact-open sizing, fractional
orders, and uncharged small negative cash. A research-only account now explicitly
handles these matters; live modules/settings were not repurposed.

Frozen QQQ/GLD/IEF data are complete on common sessions, with no missing/duplicate
prices or OHLC violations in the audited cache. QQQ starts 1999-03-10, GLD
2004-11-18, IEF 2002-07-30. Raw price/dividend/split data were separately retrieved
without changing existing caches. Raw dividend reconstruction agrees with QQQ's
adjusted total return to 0.00343% of terminal wealth over 2007+ (maximum one-day
difference 0.71 bp). This supports a gross-dividend-reinvested benchmark; it is not
independent institutional-grade vendor validation. Yahoo history can be revised.

The 2021+ intraday sample contains many prior experiments, including a 480-config
ORB search. At least 89 previous result bundles and research documents already
use the recent history. **There is no credible untouched holdout.** The four fresh
late-September sessions are insufficient. The ETF set avoids today's surviving
stock constituent list, but asset/hypothesis choice still reflects observed history.

## Frozen protocol and interpretation

The [protocol](protocol.md) and
[configuration](../../config/experiments/research_cycle_2026_10_01.yaml)
precede candidate calculations. Ranked hypotheses, mechanisms and falsifiers are
recorded there. Nine signal variants only: SMA 100/200/300 trend; 15/20/25% volatility
targets with SMA200 and a 1.5x cap; 126/189/252-session cross-asset momentum skipping
21 sessions and gated by SMA200. Central controls and stress rules were fixed too.
The studies by [Moskowitz, Ooi and Pedersen](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)
and [Moreira and Muir](https://conference.nber.org/confer/2016/LTAMs16/Moreira_Muir.pdf)
motivate trend persistence and reducing risk during high volatility. They do not
validate these particular ETF implementations.

Development is 2007–2015, validation 2016–2020, historical confirmation 2021–Sep2026.
Selection maximizes development CAGR among candidates with at least 10% smaller
drawdown than QQQ. It locked `rotation_126` before validation. Validation failed;
selection was retained. Final confirmation and all predefined stresses were run
as one batch, without retuning. [Implementation notes](implementation_notes.md)
record one added zero-transaction-cost diagnostic and hash-integrity hardening.

The starting NAV date is **2006-12-29**, first fill **2007-01-03**, final mark
**2026-09-30**. All full-period comparisons share those dates. Warmup history is
excluded from returns. Subperiod metrics include the preceding NAV, preserving
their first daily return. Confirmation is historical reuse, not genuine out of sample.
Acceptance requires both objectives in full history, validation and confirmation,
plus joint adverse stress; no result qualifies.

## Net performance and curves

| Strategy | Net CAGR | Max DD | DD days | Sharpe | Sortino | Mean gross | Turnover/yr | Orders |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qqq_total_return | 16.34% | -53.40% | 1134 | 0.72 | 1.02 | 100.00% | 0.05 | 1 |
| qqq_buy_hold | 16.29% | -53.05% | 1134 | 0.72 | 1.02 | 99.63% | 0.05 | 1 |
| trend_200 | 11.41% | -28.14% | 782 | 0.62 | 0.85 | 82.32% | 1.45 | 29 |
| voltrend_20 | 11.95% | -33.91% | 747 | 0.58 | 0.80 | 99.46% | 2.42 | 186 |
| voltrend_25 | 13.34% | -36.47% | 748 | 0.59 | 0.81 | 111.90% | 2.39 | 161 |
| rotation_126 | 11.12% | -35.96% | 962 | 0.59 | 0.81 | 93.59% | 6.53 | 135 |
| rotation_252 | 11.85% | -30.94% | 875 | 0.62 | 0.85 | 93.70% | 4.73 | 97 |
| qqq_vol_only | 16.22% | -38.70% | 891 | 0.72 | 1.01 | 111.09% | 1.48 | 206 |
| qqq_125 | 19.03% | -63.02% | 1175 | 0.70 | 1.00 | 124.52% | 0.17 | 77 |
| equal_weight | 10.16% | -21.66% | 755 | 0.87 | 1.24 | 98.52% | 0.20 | 145 |

DD days are longest calendar time underwater, including unrecovered episodes;
orders count filled adjustments, not round trips. Turnover is sum of absolute
trade notional/pretrade NAV per year (not divided by two). Mean gross is daily
closing holdings/NAV. `qqq_total_return` is a deliberately stricter, fully invested,
fractional gross benchmark with zero entry friction; `qqq_buy_hold` is the net
whole-order account. Both enter at the same first open. Dividends are reinvested
in both; terminal holdings are marked without a sale. Comparing against the net
benchmark instead does not rescue the nine candidates.

[Open standalone interactive equity and drawdown curves](results/curves.html).
The HTML contains Plotly inline and works offline. Exact daily values:
[equity CSV](results/full_equity.csv), [drawdown CSV](results/full_drawdown.csv).

| Period | Strategy | CAGR | Max DD | Both targets |
| --- | --- | --- | --- | --- |
| development | trend_200 | 10.08% | -26.22% | False |
| development | voltrend_20 | 11.70% | -22.76% | False |
| development | rotation_126 | 13.68% | -22.64% | True |
| development | qqq_vol_only | 13.74% | -38.70% | True |
| development | qqq_total_return | 12.06% | -53.40% | False |
| validation | trend_200 | 11.91% | -28.14% | False |
| validation | voltrend_20 | 10.96% | -29.93% | False |
| validation | rotation_126 | 7.78% | -35.96% | False |
| validation | qqq_vol_only | 19.43% | -29.88% | False |
| validation | qqq_total_return | 23.94% | -28.56% | False |
| confirmation_reused | trend_200 | 13.08% | -20.11% | False |
| confirmation_reused | voltrend_20 | 13.22% | -19.41% | False |
| confirmation_reused | rotation_126 | 10.10% | -30.34% | False |
| confirmation_reused | qqq_vol_only | 17.40% | -28.92% | True |
| confirmation_reused | qqq_total_return | 16.77% | -35.12% | False |

The selected rotation's development success (13.68% vs 12.06% QQQ CAGR, with much
less drawdown) reverses in validation (7.78% vs 23.94%). The entire neighborhood
fails later; changing to another lookback after seeing that would be selection bias.

## Exposure, leverage and signal attribution

| Strategy | CAGR | Max DD | Mean gross | QQQ beta | OLS alpha/yr |
| --- | --- | --- | --- | --- | --- |
| trend_200 | 11.41% | -28.14% | 82.32% | 0.61 | 0.85% |
| voltrend_20 | 11.95% | -33.91% | 99.46% | 0.69 | 0.63% |
| rotation_126 | 11.12% | -35.96% | 93.59% | 0.40 | 4.06% |
| qqq_125 | 19.03% | -63.02% | 124.52% | 1.26 | -0.43% |
| qqq_vol_only | 16.22% | -38.70% | 111.09% | 0.92 | 1.07% |
| equal_weight | 10.16% | -21.66% | 98.52% | 0.31 | 3.54% |
| matched_rotation_126 | 15.59% | -50.82% | 95.01% | 0.94 | -0.03% |
| matched_trend_200 | 13.45% | -45.64% | 81.81% | 0.81 | -0.32% |
| matched_voltrend_20 | 16.48% | -54.67% | 101.60% | 1.02 | -0.09% |

Matched controls hold a constant QQQ weight learned only from each strategy's
development mean gross exposure; that weight is frozen thereafter. Matching total
gross exposure across different assets does not equalize market beta. The OLS
alpha is descriptive, not evidence of skill, and omits gold/bond factors. Thus the
rotation's positive QQQ-regression intercept cannot establish a timing edge.
The equal-weight three-ETF control reaches 10.16% CAGR/-21.66% DD versus rotation's
11.12%/-35.96%; most diversification benefit is available without selecting winners.

The SMA200 rule holds about 82% average gross exposure; its matched QQQ control
grows faster (13.45% vs 11.41%) with deeper drawdowns. Volatility-only QQQ has about
111% average gross and beta 0.92, so its near-match is not a free gain at the same
exposure. Fixed 1.25x QQQ demonstrates how much apparent growth can come from
leverage alone. The trend gate adds no return advantage in this cycle.

## Robustness, costs and uncertainty

| Variant | CAGR | Max DD | DD reduction | Both targets |
| --- | --- | --- | --- | --- |
| trend_100 | 10.94% | -27.93% | 47.70% | False |
| trend_200 | 11.41% | -28.14% | 47.30% | False |
| trend_300 | 11.92% | -28.32% | 46.96% | False |
| voltrend_15 | 9.65% | -26.76% | 49.90% | False |
| voltrend_20 | 11.95% | -33.91% | 36.50% | False |
| voltrend_25 | 13.34% | -36.47% | 31.72% | False |
| rotation_126 | 11.12% | -35.96% | 32.67% | False |
| rotation_189 | 9.75% | -30.31% | 43.24% | False |
| rotation_252 | 11.85% | -30.94% | 42.06% | False |

The nine neighbors are all retained. There is no isolated full-period winning
parameter. Annual expanding-window selection (from 2016, training only through the
prior December) chooses rotation in 2016–17 and voltrend25 thereafter:

| Strategy | CAGR | Max DD |
| --- | --- | --- |
| annual_selector | 12.40% | -35.03% |
| qqq_total_return | 20.30% | -35.12% |

This selector also fails. Choices, actual traded account and equity paths are saved;
performance is not computed by splicing independently capitalized strategy returns.

| Scenario | Strategy | CAGR | Max DD | Both targets |
| --- | --- | --- | --- | --- |
| tiered_5bps | rotation_126 | 11.12% | -35.97% | False |
| tiered_5bps | qqq_vol_only | 16.28% | -38.62% | False |
| fixed_10bps | rotation_126 | 10.77% | -36.49% | False |
| fixed_10bps | qqq_vol_only | 16.12% | -38.81% | False |
| fixed_20bps | rotation_126 | 10.04% | -37.41% | False |
| fixed_20bps | qqq_vol_only | 15.99% | -38.82% | False |
| delay_2 | rotation_126 | 11.78% | -37.00% | False |
| delay_2 | qqq_vol_only | 16.02% | -39.26% | False |
| delay_5 | rotation_126 | 11.67% | -30.32% | False |
| delay_5 | qqq_vol_only | 15.46% | -41.80% | False |
| funding_plus_200bps | rotation_126 | 11.12% | -35.96% | False |
| funding_plus_200bps | qqq_vol_only | 15.71% | -38.70% | False |
| fractional | rotation_126 | 11.18% | -36.08% | False |
| fractional | qqq_vol_only | 16.23% | -38.60% | False |
| broker_cash_interest | rotation_126 | 11.13% | -35.94% | False |
| broker_cash_interest | qqq_vol_only | 16.24% | -38.70% | False |
| joint_adverse | rotation_126 | 10.70% | -38.60% | False |
| joint_adverse | qqq_vol_only | 15.27% | -39.43% | False |
| zero_transaction_costs | rotation_126 | 11.56% | -35.49% | False |
| zero_transaction_costs | qqq_vol_only | 16.40% | -38.51% | True |

Baseline is Fixed pricing, 5 bp per-side aggregate spread/slippage, actual whole
trade shares, lagged Fed funds +150 bp borrowing. Fixed reflects the existing
paper-account fee observation; Tiered is a sensitivity. Joint adverse is 20 bp,
two-session signal delay, and funding +200 bp. Slippage is an assumption, not a
measured opening fill. No tested central or locked candidate is rescued by zero
transaction costs.
The volatility-only control barely passes full history with zero transaction
costs (16.40% CAGR), then fails at modeled costs (16.22%) and falls to 15.27% under
joint adverse conditions. It is a useful risk-control lead, not established alpha.

| Strategy | Fees | Slippage | Funding | Max gross | Resized purchases |
| --- | --- | --- | --- | --- | --- |
| qqq_total_return | $0 | $0 | $0 | 1.00 | 0 |
| qqq_buy_hold | $1 | $2 | $0 | 1.00 | 0 |
| trend_200 | $33 | $202 | $0 | 1.00 | 1 |
| voltrend_20 | $195 | $426 | $2,531 | 1.63 | 8 |
| voltrend_25 | $172 | $507 | $5,291 | 1.63 | 16 |
| rotation_126 | $158 | $1,054 | $0 | 1.00 | 3 |
| rotation_252 | $112 | $669 | $0 | 1.00 | 1 |
| qqq_vol_only | $214 | $395 | $3,854 | 1.63 | 11 |
| qqq_125 | $77 | $34 | $7,331 | 1.38 | 9 |
| equal_weight | $143 | $23 | $0 | 1.00 | 23 |

Fee schedules use the repository's explicit Fixed/Tiered, exchange/clearing and
SEC/FINRA models, applied uniformly across historical dates rather than falsely
claiming reconstructed tariffs. See [IBKR commissions](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php).
Funding uses actual debit cash and ACT/360 calendar days, not leverage times a
flat annual penalty; Fed funds is a proxy for [IBKR's benchmark-plus-spread rates](https://www.interactivebrokers.com/en/trading/margin-rates.php).
The last cached DFF observation (2026-09-24) is carried through Sep30. Cash earns
zero base; the [broker-scaled cash-interest sensitivity](https://www.interactivebrokers.com/en/accounts/fees/pricing-interest-rates.php)
has little impact and reflects thresholds/account size approximately.

All intentional targets are <=1.5x, but drift can exceed this (max 1.63x in the
volatility-only control). No base open/close exposure exceeds 2x. This does not
certify intraday margin or house requirements. Previous-close order sizing reserves
1% cash on unlevered decisions. The resized-purchase counts disclose cases where
opening gaps/postcost exposure required reducing a planned buy after observing the
open; these are approximate opening-session fills, not exact MOO auction fills.

Fresh $5,000 restarts test present-day small-account sizing rather than a large
account grown from 2007. Restart benchmarks enter at the new first open; their
first overnight return therefore differs from continuous subperiods:

| Fresh $5k account | Strategy | CAGR | Max DD |
| --- | --- | --- | --- |
| validation_5k_restart | rotation_126 | 8.20% | -35.37% |
| validation_5k_restart | qqq_vol_only | 19.89% | -30.14% |
| validation_5k_restart | qqq_total_return | 24.49% | -28.56% |
| confirmation_5k_restart | rotation_126 | 9.61% | -30.38% |
| confirmation_5k_restart | qqq_vol_only | 17.08% | -29.65% |
| confirmation_5k_restart | qqq_total_return | 16.69% | -35.12% |

Regime checks expose why drawdown reduction is not stable across crises:

| Regime | Strategy | CAGR | Max DD |
| --- | --- | --- | --- |
| financial_crisis | rotation_126 | 15.06% | -22.64% |
| financial_crisis | qqq_vol_only | 6.91% | -38.70% |
| financial_crisis | qqq_total_return | 2.13% | -53.40% |
| recovery | rotation_126 | 13.00% | -22.49% |
| recovery | qqq_vol_only | 17.33% | -20.56% |
| recovery | qqq_total_return | 17.39% | -16.10% |
| pre_covid | rotation_126 | 4.76% | -24.08% |
| pre_covid | qqq_vol_only | 20.41% | -22.71% |
| pre_covid | qqq_total_return | 18.50% | -22.80% |
| covid | rotation_126 | 20.74% | -28.24% |
| covid | qqq_vol_only | 15.56% | -29.88% |
| covid | qqq_total_return | 48.29% | -28.56% |
| 2021 | rotation_126 | 26.90% | -10.65% |
| 2021 | qqq_vol_only | 30.22% | -11.39% |
| 2021 | qqq_total_return | 27.44% | -10.85% |
| inflation_2022 | rotation_126 | -19.95% | -20.64% |
| inflation_2022 | qqq_vol_only | -25.23% | -27.88% |
| inflation_2022 | qqq_total_return | -32.67% | -34.83% |
| recent | rotation_126 | 15.38% | -30.34% |
| recent | qqq_vol_only | 28.74% | -22.54% |
| recent | qqq_total_return | 32.06% | -22.77% |

QQQ-only 2001–2006 diagnostic (starting NAV 2000-12-29, after the 2000 crash had
already begun):

| Strategy | CAGR | Max DD |
| --- | --- | --- |
| trend_200 | 4.32% | -18.45% |
| voltrend_20 | 2.37% | -26.51% |
| qqq_vol_only | 1.24% | -37.99% |
| qqq_total_return | -4.70% | -70.40% |

Trend helps greatly in this sustained bear market, but that previously observed
period was not used to overturn the failed later validation. This is not a test
of the complete peak-to-trough 2000 crash, and GLD is not synthetically backfilled.

Paired circular-block bootstrap on 2016–Sep2026, 2,000 resamples, 63 sessions/block,
seed 20261001:

| Variant | Log growth gap/yr | 95% low | 95% high | Familywise p |
| --- | --- | --- | --- | --- |
| trend_100 | -7.52% | -14.38% | -0.37% | 1.000 |
| trend_200 | -6.49% | -12.95% | 0.22% | 1.000 |
| trend_300 | -5.49% | -10.67% | -0.18% | 1.000 |
| voltrend_15 | -8.89% | -16.82% | -1.16% | 1.000 |
| voltrend_20 | -6.82% | -14.99% | 1.19% | 1.000 |
| voltrend_25 | -5.90% | -14.41% | 2.23% | 0.996 |
| rotation_126 | -9.68% | -20.53% | 1.17% | 1.000 |
| rotation_189 | -7.90% | -18.49% | 2.56% | 0.999 |
| rotation_252 | -6.91% | -17.88% | 4.49% | 0.992 |

The intervals concern annualized **log-growth differences**, not percentage-point
CAGR differences. The centered max-statistic test covers all nine signal variants;
it does not adjust away the repository's earlier experiments, chosen ETF universe,
or publication selection. No positive excess-growth claim is significant. The
selected rotation has a -9.68% annual log-growth gap with a wide interval spanning
zero; resampled simultaneous-objective frequency is only 2.95%. This frequency is
not a probability of future success. Dependence across long market regimes and
vendor/execution uncertainty remain beyond what this bootstrap can establish.

Metric conventions: CAGR uses elapsed calendar days/365.25. Sharpe is daily mean
excess return divided by sample standard deviation of daily excess return, times
sqrt(252). Excess return subtracts lagged DFF times actual elapsed days/360.
Sortino uses the same numerator and sqrt(mean(min(excess,0)^2)) across **all** days,
times sqrt(252). The rate is a risk-free proxy; account cash follows its separate
modeled policy. Zero-rate Sharpe is also in the CSVs for legacy reconciliation.

## Decision and evidence that would change it

Reject the selected rotation and trend-gated variants as solutions to the stated
joint objective. Preserve simple trend as a documented crisis-protection tradeoff,
not a claim of higher growth. Prefer **further research**, with the existing fixed
volatility-only control as the narrow lead: its risk reduction is meaningful, but
its return edge disappears under realistic costs, worse financing or slower fills.
Do not tune its volatility window/target further on this history in this cycle.

A subsequent cycle should pre-register the unchanged 63-day/20%/1.5x volatility
rule on additional liquid equity ETFs and prospective observations, with a real
dividend/whole-share cash ledger and measured opening execution. Require growth
above the identical-period QQQ reference, at least 10% lower drawdown, persistence
under adverse costs, and economically positive excess growth outside the selected
asset/regime. A repeatable failure should reject the return-enhancement claim;
success across independent regimes could justify execution-only paper evaluation.
Paper trading alone will not establish a multi-decade drawdown claim.

Remaining limitations: reused history and multiple testing; selected asset set;
ideal fractional gross dividend reinvestment on adjusted prices (not pay-date cash
or a whole-share DRIP ledger); no dividend withholding/personal taxes, consistently
for benchmark and strategies; daily resolution and approximate opening fills;
historical tariff/funding proxies; and no independently sourced long-history price
validation. These matter especially for a marginal control near the benchmark.

## Reproduction and artifacts

Run from repository root using the pinned existing environment. Exact replay is
offline once frozen inputs are present. `uv run --no-sync python` may replace the
Windows interpreter path below.

```powershell
.venv/Scripts/python.exe research/qqq_research_cycle/reproduce_legacy.py
.venv/Scripts/python.exe research/qqq_research_cycle/prepare_inputs.py
.venv/Scripts/python.exe -m horizon_trader.backtest.research_cycle --stage develop
.venv/Scripts/python.exe -m horizon_trader.backtest.research_cycle --stage validate
.venv/Scripts/python.exe -m horizon_trader.backtest.research_cycle --stage confirm
.venv/Scripts/python.exe research/qqq_research_cycle/make_report.py
.venv/Scripts/python.exe research/qqq_research_cycle/verify_results.py
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp data/tmp/cycle_verification
```

`fetch_raw.py` is the explicit network retrieval step if reconstructing missing raw
inputs. Exact old prices require the frozen snapshot, since Yahoo can revise data.
`prepare_inputs.py` preserves an existing snapshot. Inputs are in git-ignored
`data/research_cycle_2026_10_01/inputs/` and **must be preserved/copied with this
research** for exact replay; SHA256s are stored in its manifest. Stage manifests
record Python/numpy/pandas and code/config hashes. The runner validates input and
protocol hashes and refuses a changed locked selection. No API keys are in artifacts.

The [experiment ledger](results/experiment_ledger.csv) contains 612 rows
covering every candidate/control, period, stress, restart, dotcom and walk-forward
result with rejection reasons. These rows are related diagnostics, not independent
trials; the signal search was nine variants. Additional files include all orders,
daily cash/cost/exposure accounts, annual and regime metrics, uncertainty, selected
parameters, legacy snapshots, and the self-contained curves. Files in the original
dirty worktree were preserved; only clean legacy simulator/analytics code and their
tests were modified alongside new research files.

Verification: the full repository suite passed 393 tests, and three subsequently
added statistical tests also passed. Changed/new code passes Ruff. The saved
development account is replayed bit-exactly by `verify_results.py`, which also
checks capital identities, signal/fill ordering, comparison dates and trial coverage.
Three existing numpy warnings occur in the fundamentals test with insufficient
observations. No rendering screenshot was captured; curves are generated by Plotly
from the same saved daily equity used for the tables.
