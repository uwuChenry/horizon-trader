# Implementation decisions

- All orders are research simulations. The broker observer only connects read-only
  to DU accounts. The existing paper adapter/strategy ledgers are not repurposed.
- A pending ORB stop-limit reserves gross buying power from the 09:35 candidate
  decision until fill/cancellation, including historical candidates with no fill.
  This tightens the initial protocol's synchronous-order simplification. Other
  orders fill/reject synchronously; partial fills and acknowledgement latency are
  not broker-calibrated. No prices are invented for missing held-asset minute marks.
- Ex-date entitlements use nominal shares. Dividend payment dates are fetched
  separately from Massive; missing dates use the protocol's 45-day proxy. Amounts
  are from frozen Yahoo actions. Gross dividends are the baseline, 30% withholding
  a sensitivity, not a claim about the owner's treaty status. Cash earns zero.
- The account uses a 2x gross model. A mark drift above it is flagged even if no
  additional order is sent; this is stricter than merely testing initial orders,
  but does not model actual broker liquidation or intraday house margin changes.
  The volatility-managed QQQ control targets at most 1.5x and allows drift up to
  the same 2x control limit overnight, unlike the unlevered daily core.
- Baseline ORB inherits saved stop-limit fills/exit slippage. Delayed entries use
  all top candidates, including baseline nonfills: place at 09:35 plus latency,
  require a subsequent trigger, then a later-minute trade-through of the limit.
  They use a 5c adverse stopped-exit allowance. This is
  an assumption, not new quote evidence. Stops in the entry bar count as hit.
- Baseline ORB remains working to the session close, matching the historical
  baseline. The live adapter's 15:44 cutoff is a documented implementation gap.
- Added one clearly labeled no-minimum-commission diagnostic after the plumbing
  runs showed large capital sensitivity. It cannot select a strategy or certify
  executable performance. Signal parameters and the two allocations remain fixed.
- The 2024 restarts reset all four starting balances; they do not reuse wealth
  accumulated since 2021. The small-account comparisons are all reported, not
  optimized to a winning starting balance.
- Older Massive entitlement HEAD checks returned HTTP 403 for 2017-01-03 and
  2020-03-16. No subscription was changed. Older validation therefore covers daily
  controls only, using existing ETF history. Full older intraday testing remains
  contingent on obtaining access; it is not replaced with synthetic intraday bars.
- The observer recorded a successful connection and account fields, but the first
  run received error 354 for all ten ETF feeds and no quotes or executions.
  Account balance was approximately $1M: that does not verify small-account margin.
  The owner is configuring live-to-paper market-data sharing. All quote rows retain
  their market-data type and source timestamp; missing values become JSON null.
- The installed ib_async wrapper sets `ticker.time` from socket-arrival time,
  not an exchange quote timestamp. Quotes therefore label it `api_update_time`
  and explicitly leave `exchange_quote_time` unknown. Execution timestamps come
  from IBKR's execution report. Other clients' orders/completions/executions are
  polled read-only every 60 seconds as well as listening to available API events;
  these polling observations cannot measure subsecond broker latency.
