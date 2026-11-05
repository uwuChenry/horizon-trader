# Entry time of day for short swing trades: protocol

Written 2026-11-05, before any result was computed.

## Question
For long holds of 1-5 trading days in high-beta tech, does the time of day you buy matter, and
is the forecast journal's 15:00 ET entry a good or a bad time?

## Setup
- Tickers: SPY, QQQ, SMH, TQQQ, SOXL, NVDA, AMD, AVGO, MU, TSLA, META.
- Period: every day of Massive minute bars on disk (Oct 2021 onward).
- Entry times (ET): 9:35, 10:00, 11:00, 12:00, 13:00, 14:00, 15:00, 15:30, 15:55, at the open of
  the minute bar starting then. Plus **next open**: wait and buy at tomorrow's official open.
- Exit: the official close (Massive daily close) N trading days after the entry day,
  N = 1, 3, 5. Every entry time on a day shares the same exit, so differences between entry
  times are purely the price path from the entry until that day's close.
- Unadjusted prices, so any window that contains a day with |open / previous close - 1| > 35%
  (splits) is dropped.
- No costs: spreads on these names are about 1 bp, the same at any time of day.

## Pre-registered test
- **H1:** for longs, late entries beat the 9:35 entry. Pooled across tickers (the equal-weight
  average return per day), the mean of (15:00 entry - 9:35 entry) is > 0 with t > 2 in BOTH
  halves: Oct 2021 - Dec 2023 and Jan 2024 onward. (It doesn't depend on N, since the exits are
  shared.)
- **H2:** buying at 15:00 beats waiting for the next open: pooled mean of (15:00 entry, exit
  close of day 1) minus (next-open entry, same exit) > 0 with t > 2 in both halves.

## Descriptive
- Mean and median return from each entry time to the fixed exits, per ticker.
- **Timing luck:** the average absolute gap between the price at a random entry time and the
  day's mean entry price, in %, to show how much a single trade's entry can swing.

## Exploratory (labelled as such, not tests)
- Conditional on the move by 15:00 (from the previous close): down more than 2% or up more than
  2%. Return from 15:00 to the close and to the next day's close: do high-beta dips into 15:00
  keep falling or bounce?

## Not covered
Option bid/ask by time of day (no option history on disk). Options are known to have their
widest spreads in the first 15-30 minutes, which argues against buying options at the open,
but this study can't measure it.
