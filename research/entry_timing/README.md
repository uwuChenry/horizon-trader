# Entry time of day for short swing trades

**Verdict:** for 1-5 day long holds in high-beta tech, **the time of day you buy doesn't matter
on average**. Buying at 15:00 vs 9:35 differed by -10 bp (2021-23, t = -1.2) and +0.5 bp
(2024+, t = 0.1), and no entry time had a significant edge into the close. Buying before the
close beat **waiting for the next open** by +21 bp a day in 2024+ (t = 3.0) but not in 2021-23
(-1 bp), so it fails the pre-registered rule. The forecast journal's 15:00 entry is fine:
nothing earlier in the day is reliably better, and buying today is at least as good as
waiting until tomorrow.

Rules: [protocol.md](protocol.md), written before any result. Code:
`src/horizon_trader/intraday/entry_timing.py`. Massive minute bars, 2021-10-04 to 2026-11-02
(1,277 days), long only, no costs.

## Tests (pooled equal-weight across 11 tickers per day)
| Test | 2021-23 | 2024+ | Passed |
|---|---|---|---|
| H1: buy at 15:00 minus buy at 9:35 | -10.5 bp, t = -1.21 | +0.5 bp, t = 0.07 | no |
| H2: buy at 15:00 minus buy at the next open | -0.8 bp, t = -0.11 | +20.9 bp, t = 2.97 | no (one half only) |

## Mean return to the close of day N, by entry time (pooled, bp)
| Hold | 9:35 | 10:00 | 11:00 | 12:00 | 13:00 | 14:00 | 15:00 | 15:30 | 15:55 | close | next open |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 day | 20.9 | 20.3 | 22.3 | 18.2 | 19.9 | 17.0 | 16.4 | 17.5 | 17.5 | 16.3 | 5.3 |
| 3 days | 52.2 | 51.6 | 53.8 | 49.7 | 51.2 | 48.2 | 47.7 | 48.7 | 48.8 | 47.5 | 36.8 |
| 5 days | 83.8 | 83.4 | 85.6 | 81.6 | 83.1 | 80.3 | 79.7 | 80.8 | 80.8 | 79.1 | 67.8 |

All entries on a day share the same exit, so the spread across a row is just the path from the
entry to that day's close. It's about 5 bp at most and statistically zero (t <= 1.5 for every
time over the full period, see `intraday_profile.csv`). The jump to "next open" is the
overnight return you skip by waiting. Per-ticker rows are in `by_time.csv`.

## Timing luck per trade
The average gap between one entry time's price and the day's typical entry price: SPY 0.24%,
QQQ 0.33%, SMH 0.49%, META 0.51%, AVGO 0.57%, NVDA 0.69%, MU 0.70%, AMD 0.76%, TSLA 0.82%,
TQQQ 0.98%, SOXL 1.55%. For a single trade that's large next to a typical 5-day move, but it's
noise: it averages out, and nothing in the clock predicts which side of it you land on.

## Exploratory (not tests)
| Move by 15:00 vs the previous close | Days | 15:00 to close | 15:00 to next close |
|---|---|---|---|
| Down more than 2% | 2,512 | +1.3 bp (t 0.5) | +23.6 bp (t 2.5) |
| Within ±2% | 8,360 | -1.7 bp (t -2.0) | +10.6 bp (t 3.2) |
| Up more than 2% | 2,918 | +5.5 bp (t 2.8) | +27.4 bp (t 3.5) |

Big up days keep drifting up slightly into the close; big down days neither keep falling nor
bounce by the close. The next-day numbers are positive in every bucket because the sample is a
semiconductor boom. Not a signal.

## Caveats
- One mostly bullish 5-year sample, dominated by semis; long only. For puts, every sign flips:
  the overnight drift works against a bearish position held overnight.
- Option bid/ask by time of day isn't measured (no option history). Spreads are widest in the
  first 15-30 minutes, so options should not be bought at the open; that argues for the
  journal's afternoon entry too.
- Bar-open fills, no spread or impact: fine for these names at journal sizes.
