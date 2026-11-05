# ORB plus EMA momentum exits — frozen before this run

Requested 2026-10-02. This is exploratory research on already-reused history,
not a fresh holdout or a change to the paper executor.

- Keep the existing 09:35 top-one stock selection, including its liquidity,
  relative-volume and non-doji filters. Do not replace a nontrading pick.
- Opening range: 09:30–09:35. EMA: 12 completed **5-minute** regular-session
  closes, with five previous sessions of warmup, adjusted into today's split
  basis. The owner confirmed 5-minute candles before results were run.
  No synthetic candles for minutes without trades; a signal requires the last
  minute of its candle to exist. Never use an unfinished candle.
- ATR is the existing **mean true range of the preceding 14 daily bars**, already
  split-adjusted and lagged. It is not intraday ATR or Wilder-smoothed ATR.
- Primary stop: **1 ATR** from the raw entry fill. Sensitivities fixed in advance:
  **0.5, 0.75, 1, 1.5, 2 ATR**. Risk stays at 1% of starting-day equity, with
  whole shares and a 2x gross sizing ceiling. The ceiling is a sizing assumption,
  not a broker margin simulation. Starting capital: $5,000.
- Four rules, each allowing at most one round trip per day:
  1. `orb`: original first-candle direction and intraminute range breakout;
     fixed stop, otherwise close auction.
  2. `orb_ema_exit`: identical entries; exit on the first completed candle
     closing across the EMA against the position, otherwise stop/close auction.
  3. `orb_ema_confirm`: buy a completed close above both opening high and EMA;
     sell short below both opening low and EMA, irrespective of opening-candle
     direction. Exit on an adverse EMA close, stop, or close auction.
  4. `selected_ema`: same selected stock, long on a close above EMA / short
     below, without a range-break requirement. Same exits. This isolates the
     user's EMA-direction idea from the opening-range confirmation.
- EMA equality neither enters nor exits. No profit target, breakeven move,
  trailing ATR stop, reentry, or automatic reversal. An EMA exit can realize a
  loss; it does not guarantee profit or capture the entire breakout.
- Close-derived decisions fill at the next available minute open, strictly
  after the signal. Stops are active from entry; gap-through stops fill at the
  worse open. For intraminute breakout entries, any same-minute stop touch counts
  as a stop (conservative ordering). Stops take priority if the exit open gaps
  through them. A later low/high cannot affect an EMA exit already filled at open.
- Main cost case: repository Fixed schedule and 5 cents adverse slippage on
  each entry/non-auction exit. Also show Tiered at 5 cents and no-cost diagnostics.
  Costs are assumptions, not new quote measurements; new signal times cannot
  reuse the old stop-limit fill measurements. Stops remain based on raw fills,
  so entry and exit slippage add to the nominal risk budget.
- Flat at the official daily close, with early sessions cut at 13:00 using
  SPY session coverage (same proxy approach as existing intraday research).
  Missing/malformed sessions are logged and excluded identically for every rule.
- Compare full history and independent $5k restarts on 2021–23 and 2024 onward.
  Preserve every trial and the full calendar, including flat days. Report net
  CAGR, drawdown, zero-hurdle Sharpe, trade count, mean gross R and exit mix.
  No automatic winner selection; inspect the 1-ATR result first, then stability.

Limitations: selected-stock research, not the shared-account replay; no historical
locates, borrow charges, queue/spread history, or subscription bills. The original
stop-limit baseline remains a separate experiment. Published technical background:
[Fidelity on EMA](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/ema)
and [ATR](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr).
