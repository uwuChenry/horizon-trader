# ORB EMA follow-up: Tiered, 1 cent, 15-minute exits

Requested by the owner after reviewing the first run on 2026-10-02. Frozen
before running this follow-up. The prior result files remain the research record.

- Use **IBKR Pro Tiered** commissions and **$0.01 per share adverse slippage**
  on each entry and each non-auction exit. Auction exits retain commissions
  and zero additional slippage, as in the earlier experiment. The slippage is
  the owner's modeling assumption, not a new measurement. Also retain a
  zero-cost diagnostic. Fixed is no longer the headline assumption.
- Change **exits only**: calculate EMA(12) from completed **15-minute**
  regular-session candles. A long exits when the 15-minute close is below that
  EMA; a short exits when above. Equality holds. The first current-session exit
  decision is at 09:45. A close-derived exit fills at the next available minute
  open (the 09:45 bar's open for the candle ending at 09:45).
- This is a 12-period EMA computed on 15-minute closes, not a five-minute EMA
  checked once every 15 minutes. Keep the same five-session split-safe warmup.
- Preserve all four entry rules: original ORB entry; original ORB entry with EMA
  management; **5-minute** range-break close plus **5-minute** EMA confirmation;
  and **5-minute** EMA direction on the selected stock. Preserve stock selection,
  entry times, one trade/day, and the original five-minute opening range.
- Keep the fixed **1 prior daily ATR** stop as the main setting, and the existing
  {0.5, 0.75, 1, 1.5, 2} daily-ATR sensitivity. Stops remain active every minute,
  including before 09:45 and between EMA decisions. Nothing trails or reverses.
- Same $5,000 initial equity, 1% risk, whole shares, 2x entry-notional ceiling,
  session close exits, conservative same-minute stop handling, and full calendar.
- Reprice the saved five-minute-exit trades at **the same Tiered/1c costs**.
  Compare those with the new 15-minute exits and the unmodified ORB control.
  Assert every entry matches between exit variants; do not confound changed
  costs with changed signals. Report gross/net results and independent starting
  balances for full history, 2021-23 and 2024 onward.
- No automatic selection among stops, new filters, or orders. Existing model
  limitations remain: reused history, unmeasured spreads/locates, no borrow costs,
  no shared-account margin simulation, and stops anchored to pre-slippage prices.

This is a follow-up to a previously observed result, not an untouched holdout.
