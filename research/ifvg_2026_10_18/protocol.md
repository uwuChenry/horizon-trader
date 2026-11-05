# IFVG: rules frozen before the first performance run

Requested October 18, 2026. This is exploratory research on previously reused
market history, not a pristine holdout, a paper replication, or a live deployment.
No parameter will be selected or changed in response to the results.

## Data and scope

- Read the existing, unadjusted Massive SPY and QQQ regular-session minute
  caches: October 4, 2021 through September 24, 2026. Do not silently refresh.
- ETFs are the available instruments; this does not test NQ/ES futures.
- Build complete five-minute candles aligned at 09:30 New York time. A candle
  becomes available at its ending time. Never use incomplete or overnight candles.
- Infer full/half sessions from SPY coverage (390/210 minutes). Exclude and log
  sessions with missing, duplicate, nonfinite or invalid OHLC bars in either ETF.
  This is retrospective data-quality screening, not a tradable missing-data rule.
- Use the full common eligible calendar, including days without trades. Record
  input hashes and coverage. No cross-day indicators or adjustment factors.

## Strategies

Primary: `ifvg_close`, five-minute candles, 2R target.

1. Bullish FVG: candle 3 low exceeds candle 1 high by at least $0.02.
   Bearish FVG: candle 1 low exceeds candle 3 high by at least $0.02.
   The zone is the interval between these two wick prices. No discretionary
   displacement, trend, liquidity sweep, or higher-timeframe filters.
2. Each gap is eligible for inversion during the next 12 five-minute candles.
   A bullish gap inverts short on the first close strictly below its lower edge;
   a bearish gap inverts long on the first close strictly above its upper edge.
   A wick alone does not invert it. All inverted gaps are consumed. If multiple
   invert together, use the most recently formed gap.
3. Signal availability must fall between 09:45 and 11:30 inclusive. Enter at the
   immediately following minute's open (09:45 for the candle ending 09:45).
   If that open is beyond the intended stop, skip that signal.
4. Stop one cent beyond the opposite edge, rounded outward to a cent. Target
   2 times the raw entry-to-stop distance, rounded away from entry to a cent.
   Protective stop and target are active immediately after entry.
5. Maximum one filled trade per instrument per day; no reentry or pyramiding.
   Exit any remaining position at the open of the last regular-session minute
   (15:59 normally, 12:59 on half days), charging normal exit slippage and fees.

Secondary: `ifvg_retest`. After the same inversion, wait up to six subsequent
five-minute candles for a touch of the near edge and a close back outside the
zone in the trade direction. Enter at the next minute open, with the same stop,
target, cutoff and daily trade cap. A close through the far edge cancels the
pending setup. Ignore new inversions while a setup is pending. The inversion
candle itself cannot count as its retest.

Controls: `breakout_close` and `breakout_retest`. A five-minute close crosses
above/below the high/low of the preceding three complete five-minute candles.
The prior range supplies the zone and the opposite-edge stop. Apply the same
entry timing, retest confirmation, costs, cutoff and exits. These are simple
alternative triggers, not perfectly matched causal controls: stops and event
times differ. Better performance alone would not isolate the gap's contribution.

Bounded sensitivity: report every strategy with 1R and 3R targets as well as the
primary 2R, without selecting a winner. Two ETFs x four strategies x three
targets = 24 configurations; cost cases are diagnostics, not additional alphas.

## Execution, sizing and costs

- Walk one-minute bars chronologically. Gap-through stops fill at the adverse
  open. A target gap fills at the target without favorable price improvement.
  If a minute touches both barriers, stop first; count these ambiguous bars.
  An open-triggered exit precedes that minute's later high/low. Intraminute
  exit timestamps identify the bar, not an exact execution second.
- Each configuration is a separate $5,000 account, whole shares, maximum 1x
  gross exposure, nominal risk budget 1% of current equity. Size using entry
  and stop slippage plus modeled round-trip fees, capped by available capital
  including entry fees. Stop gaps can still exceed planned risk.
- Gross: no fees/slippage. Main net: existing repository IBKR Pro Tiered fee
  model plus $0.01/share adverse slippage each side. Stress: Tiered plus $0.03
  each side. Slippage also applies to targets as a conservative execution
  allowance. Rates are the repository's fixed research assumptions across
  history, not a historical fee reconstruction or a new pricing verification.
- Also calculate gross P&L on the exact net positions, separating costs from
  the different compounding/sizing of the standalone zero-cost account.
- No interest, borrow/locate costs, taxes, subscriptions, account margin or
  settlement simulation. Short availability is assumed. Idle cash earns zero.

## Evaluation

- Full period, independent $5,000 restarts through 2023 and from 2024 onward.
  These are chronological checks on reused data, not untouched validation.
- Report trades, win rate, average gross/net R, net dollars per trade, profit
  factor, total return, CAGR, daily Sharpe against zero, max drawdown, costs,
  skipped zero-share entries and ambiguous exits. Preserve all configurations.
- Report calendar-year returns and long/short breakdowns for the primary 2R
  net case. Show equity and drawdown charts, and save trade-level evidence.
- For 2R net results use 2,000 circular block-bootstrap samples of 20 sessions,
  seed 20261018, for mean daily return and paired return differences against
  the corresponding breakout control. Intervals are descriptive, unadjusted
  for multiple comparisons; never treat the most favorable row as confirmation.
- A credible candidate should be net positive in both chronological periods,
  withstand cost/target sensitivity, and improve on its control. Passing these
  screens would still require new forward data and actual execution evidence.

Background: [direct IFVG vendor study](https://www.telonicstrading.com/research-ifvg.html),
[related FVG working paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7148099).
This experiment independently implements the explicit rules above.
