# ORB exit diagnostics, 2026-10-02

Descriptive follow-up requested after the exit experiments. No new strategy is
selected or optimized. Analyze the **same 1,001 original ORB entries**, 1 daily
ATR stop, with hold-to-close, 5-minute EMA exits, and 15-minute EMA exits.
Preserve Tiered and assumed 1c slippage on entries/non-auction exits.

Definitions fixed before reading these new diagnostics:

- Exit mix uses **all triggered trades** as denominator, not trading sessions.
  Report stops, EMA exits, closing-auction exits and modeled net win rate.
- Stop time: New York bar-start timestamp, approximate to a minute. Report both
  clock time and elapsed time from entry. Clock bins: before 10:00, 10:00-10:30,
  10:30-11:00, 11:00-12:00, 12:00-14:00, 14:00-close. Elapsed bins: under 5,
  5-15, 15-30, 30-60, 60-120, 120+ minutes. Half-open intervals, so a stop
  exactly 30 minutes after entry goes in 30-60. Include all no-trade sessions
  in uncertainty resampling, and report stop-bin counts as a fraction of all
  stop-outs and of trades. Also report counts/positions alive at each elapsed-bin
  start; these are conditional descriptive rates, not forecasts.
- For **EMA exits only**, measure (a) any later favorable price; (b) another
  0.25R/0.5R/1R above the exit in the original trade direction; (c) a new favorable
  extreme beyond the pre-exit high/low; and (d) the actual result of retaining
  the original ATR stop and otherwise closing at the auction.
- Distinguish full remaining-session excursions (ignoring subsequent stop hits)
  from excursions **before the original stop**. EMA exits occur at bar open,
  so that bar's later range is eligible. For a later stop minute, only its open
  and earlier bars are unambiguously available before the stop. If a threshold
  appears only in the stopping minute's high/low, report a range, not an assumed
  favorable ordering. A gap through the stop ends the position at that open.
- Counterfactual net comparisons use the same shares for both exits: the original
  ORB portfolio's quantity on that date. This removes different compounded wealth
  from the cost comparison. Normalize dollar changes by shares times stop distance
  for R. Summary win rates for each strategy use its own saved-model sizing.
- For original stop-outs, show later recovery to entry and final-close recovery,
  explicitly ignoring the stop afterward. Exclude the stop minute's later high/
  low because its ordering is unknown. These are descriptive recoveries, not a
  no-stop strategy recommendation or proof that the stop should be removed.
- Report gross win/loss size, profit factor, and gain concentration in the biggest
  5% of trades. Concentration is an explanation, not a hindsight filter.
- Uncertainty: 2,000 circular paired bootstrap samples of 21 trading sessions,
  fixed seed 20261002, 95% percentile intervals. Rates use resampled numerator
  and denominator counts. These intervals condition on this reused sample and
  model; they do not correct prior strategy selection or prove live profitability.

Save per-trade diagnostics privately under `data/orb_ema_2026_10_02/`; save summary
tables, report, source hashes and an offline chart for review. Future optimization
should be a separately specified experiment, not silently fitted to these outcomes.
