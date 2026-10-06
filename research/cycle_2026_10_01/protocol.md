# Protocol fixed before new candidate performance was calculated

Date: 2026-10-01. User target retained: net CAGR greater than QQQ and maximum
drawdown magnitude at most 90% of QQQ's on identical dates. No guarantee of success.
Configuration: `config/experiments/research_cycle_2026_10_01.yaml`.

## Scope and ranked hypotheses

1. **QQQ volatility sizing plus a long-term trend gate.** Volatility clusters; risk
   need not be compensated equally in volatile periods. Monthly sizing at target
   volatility / trailing 63-session volatility, capped at 1.5x, with zero equity
   exposure below the 200-session SMA, may preserve compounded growth and avoid
   sustained bear markets. The 15/20/25% volatility targets are the ONLY neighbors.
   Reject the claimed timing benefit if an exposure-matched QQQ control is as good,
   funding destroys the return advantage, or the advantage fails validation.
2. **Simple QQQ trend/cash.** Slow diffusion and institutional adjustment may produce
   persistent trends. Monthly QQQ exposure of 100% above its SMA, otherwise cash.
   Windows 100/200/300 sessions. This also supplies a simple risk-management control.
   Whipsaws and missing fast recoveries can falsify it; lower drawdown alone does
   not satisfy the return objective.
3. **Cross-asset momentum rotation.** Gradual macroeconomic repricing can favor
   different assets at different times. Hold the strongest positive 12-minus-1
   month momentum among QQQ, GLD and IEF, subject to its 200-day SMA; otherwise
   cash. Only 126/189/252-session lookbacks, all skipping 21 sessions, top one.
   Compare with equal weight in the same assets to separate diversification from
   timing. Gold and Treasuries can fail as diversifiers; inflation is a key stress.

These are adaptations of existing ETF momentum/volatility sleeves, not paper
replications. The ETF set avoids today's constituent survivor lists; its choice
still reflects known assets/history. Intraday research is deferred because its
2021+ sample is short and heavily mined (including a 480-configuration ORB sweep),
and the existing QQQ noise strategy was chosen after SPY disappointed. Long daily
history offers 2008, 2020 and 2022, with a separate QQQ-only dotcom diagnostic.

Mechanisms informed by [Moskowitz, Ooi and Pedersen (2012)](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)
and [Moreira and Muir (2016 working paper)](https://conference.nber.org/confer/2016/LTAMs16/Moreira_Muir.pdf).
These sources do not establish an edge for these particular ETF rules.

## Chronology, selection and acceptance

- Warm indicators on all preceding available data; primary initial NAV 2006-12-29,
  first executable session in 2007, end 2026-09-30. Every comparison has identical
  initial valuation and return intervals. Dates are not chosen from performance.
- Development: 2007-2015. Evaluate all nine variants and four controls, then lock
  one candidate: highest development net CAGR among variants whose drawdown
  magnitude is <=90% of QQQ's. If none qualifies, highest development Calmar,
  labeled an objective failure. Lexical name breaks ties. No subsequent retuning.
- Validation: 2016-2020. Assess the locked choice and predeclared central variants
  and neighbors. If it fails, retain the failure; do not select a replacement.
- Historical confirmation: 2021-2026-09-30, accessed as one final batch after the
  selection is written. **NOT an untouched holdout**: earlier repository work has
  used it extensively. Older development/validation are reused history too.
  There is no credible untouched holdout; only future observations can supply it.
- Continuous $5,000 account across the full history; subperiods preserve preceding
  NAV/holdings and initial return. Separately restart $5,000 at validation and
  confirmation boundaries to expose small-account rounding/commission effects.
- Secondary expanding-window annual selection from 2016: apply the same selection
  rule using only previous-year-end evidence, then trade selected signals in one
  account. Parameters and selection rule fixed here, no reoptimization of selector.
- Historical objective pass requires BOTH CAGR and drawdown targets in full history,
  validation, and confirmation, surviving joint adverse cost/delay/funding stress.
  Even a pass is preliminary. Any observed open/close leverage >2 invalidates a
  practical levered claim pending a proper margin-event replay.

## Execution, accounting and diagnostics

- Monthly decisions use the **first trading day's close**, as existing sleeves do;
  trade at the next session's open. Initial allocation uses the initial NAV day's
  available close. Hold quantities between decisions. No daily target resetting.
  Audit clarification recorded before candidate runs: size intended share orders
  using previous-session closing NAV/prices, not the unknown future opening fill.
  Reserve 1% cash for unlevered allocations. If an opening gap still makes an order
  unaffordable, reduce it and record the adjustment. This models an opening-session
  market order with an affordability check, not a guaranteed MOO-auction fill.
- Total-return adjusted open/close series, including reinvested gross dividends;
  raw opening prices used for order-share sizing and per-share charges. Whole
  trading shares, fractional automatic dividend reinvestment modeled by total-return
  units. This is a gross-tax total-return convention, not a dividend pay-date ledger.
  Signal continuity and split/dividend provenance will be checked. If raw history
  cannot be acquired, disclose the approximation and restrict practical conclusions.
- $5,000 initial cash, no deposits, no shorts. Fixed broker fees baseline because
  the repository's actual paper-account what-if quoted Fixed pricing; Tiered is a
  sensitivity. Five basis points per side aggregate spread/slippage baseline,
  10/20 bps stress. Existing explicit regulatory/exchange fee schedules are modeled
  uniformly through history, not claimed as reconstructed historical tariffs.
- Cash earns zero base (conservative for growing accounts); broker-scaled cash
  interest sensitivity. Actual negative cash pays lagged Fed funds +150 bps,
  ACT/360 calendar-day accrual including weekends; +200 bps spread stress.
  Fed funds proxy is not the exact historical IBKR benchmark. Last cached DFF
  observation may be carried forward and must be disclosed.
- Initial transaction costs included. Terminal holdings marked, not liquidated,
  for strategies and benchmark alike. No implicit uncharged margin on unlevered
  purchases. QQQ buy/hold buys once, rather than continually rebalancing to 100%.
  Also report an ideal fully invested fractional QQQ total-return path entering at
  the same first eligible open, without entry friction or the cash buffer. Use this
  stricter reference for selection/acceptance so whole-share cash drag cannot make
  the objective artificially easier.
- Sharpe: mean daily return minus lagged DFF calendar accrual, divided by sample
  standard deviation of excess returns, annualized sqrt(252). Sortino: same
  numerator over sqrt(mean(min(excess,0)^2)), sqrt(252). Also report zero-rate
  Sharpe for reconciliation with older work. DFF is a proxy, not investable cash.
- CAGR uses actual elapsed calendar years /365.25. Drawdown includes starting
  NAV; duration is elapsed calendar days from peak through recovery or sample end.
  Report mean/max gross exposure, QQQ exposure, orders, one-way absolute notional
  /pretrade NAV turnover per calendar year, dollar fees and funding, and beta/alpha.
- Controls: QQQ total-return buy/hold; fixed 1.25x monthly QQQ with funding; QQQ
  vol-only with same target and cap; monthly QQQ/GLD/IEF equal weight; for each
  central variant and locked choice, constant QQQ weight estimated from its
  DEVELOPMENT mean gross exposure and then frozen (not matched using future data).
- All nine neighbors logged, including failures. Stress on central variants,
  locked choice, benchmark, and necessary matched controls: fees, delays 2/5
  sessions, financing, fractional orders, cash yield, and joint adverse case.
- Regimes: 2007-09, 2010-15, 2016-19, 2020, 2021, 2022, 2023-end; annual returns;
  QQQ-only 2001-06 diagnostic with fully warmed 300-day SMA. This diagnostic is
  previously observed history and cannot influence selection.
- Paired circular block bootstrap (2,000 resamples, blocks 63 sessions, seed
  20261001) on later daily strategy/QQQ returns: 95% intervals for annualized log
  growth difference and empirical frequency of satisfying both objectives.
  A centered maximum-statistic bootstrap across ALL nine attempted variants
  addresses this cycle's selection. It cannot undo the repository's prior testing
  or asset-selection bias. No claim of discovery from nominal significance alone.

## Reproducibility

Freeze inputs under `data/research_cycle_2026_10_01/`, record SHA256, source dates,
package versions, config/code hashes and initial dirty worktree. Preserve all
existing artifacts and live settings. Store compact tables, ledger, report,
standalone curves and reproduction commands under `research/cycle_2026_10_01/`.
No trades, paper orders, paid data or infrastructure actions are authorized.
