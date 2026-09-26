# Combining strategies: the daily book plus intraday sleeves

Run 2026-09-25 with `uv run python -m horizon_trader.backtest.mix`. Code:
`src/horizon_trader/backtest/mix.py`. Period: Nov 2021 – Sep 2026 (the intraday data), $5k,
IBKR Pro Tiered.

## Answer first

- **The intraday sleeves are nearly uncorrelated with the daily book** (0.05 or less), as
  hoped.
- **But splitting $5k into separate pots makes things worse**: the intraday sleeves
  collapse at small sizes (ORB's Sharpe falls from 0.74 at $5k to 0.38 at $1,500) because the
  per-order minimums become a big share of each trade.
- **The fix is structural: overlay, don't split.** Intraday sleeves are flat by the close,
  so in one margin account they can size off the full equity while the daily book holds its
  positions. Same-day leverage pays no margin interest.
- **Overlaid, the combination is much better** than the daily book alone (Sharpe 0.91): with
  ORB 1.00, with QQQ noise 1.69. But **IBKR's 4x intraday limit binds** when QQQ noise is
  included, so those rows need QQQ noise sized down.
- The overlay test was **not pre-registered**, and two of its inputs were chosen after the
  fact (see the caveats). Treat it as the plan for paper trading, not a proven result.

## The sleeves

| Sleeve | What it is |
|---|---|
| Daily book | The combined daily sleeves (momentum, vol-managed SPY, trend, mean reversion) from `config/settings.yaml` |
| ORB | Stocks-in-Play ORB baseline: top-1 stock, 1 ATR stop, stop-limit entry, measured slippage, hold to the close |
| ORB candidate | ORB + relative volume ≥ 12 + no entries after 10:30 (chosen after earlier tests on the same data) |
| QQQ noise | Noise-area intraday momentum on QQQ (the other agent's replication in `intraday/market_momentum.py`): 2% vol target, max 4x, 0.5¢ slippage |

**Correlation of daily returns:**

| | Daily book | ORB | ORB candidate | QQQ noise | SPY |
|---|---|---|---|---|---|
| Daily book | 1.00 | 0.05 | 0.06 | −0.05 | 0.75 |
| ORB | | 1.00 | 0.97 | 0.01 | 0.02 |
| QQQ noise | | | | 1.00 | −0.01 |

## Pre-registered test: splitting the $5k into sub-accounts

| Blend | Capital split | CAGR | Sharpe | Max DD | Sharpe 2021–23 | Sharpe 2024–26 |
|---|---|---|---|---|---|---|
| **Daily book only (reference)** | $5,000 | 7.3% | 0.91 | −10.3% | 0.10 | 1.39 |
| Daily 70 / ORB 30 | $3,500 / $1,500 | 6.6% | 0.84 | −8.2% | 0.13 | 1.29 |
| Daily 50 / ORB 50 | $2,500 / $2,500 | 8.1% | 0.80 | −11.1% | 0.32 | 1.12 |
| Daily 70 / ORB candidate 30 | $3,500 / $1,500 | 8.4% | 1.04 | −8.4% | 0.25 | 1.53 |
| Daily 50 / ORB 25 / QQQ noise 25 | $2,500 / $1,250 / $1,250 | 6.3% | 0.94 | −5.9% | 0.39 | 1.32 |
| ORB only | $5,000 | 12.7% | 0.74 | −21.7% | 0.59 | 0.84 |
| ORB candidate only | $5,000 | 17.3% | 0.98 | −19.7% | 0.69 | 1.17 |
| QQQ noise only | $5,000 | 19.5% | 1.38 | −16.3% | 1.77 | 1.14 |
| SPY buy & hold | | 12.7% | 0.78 | −24.5% | 0.28 | 1.28 |

Splitting barely helps, or hurts, because the intraday sleeves degrade at small sizes:

| Sleeve | $1,250 | $1,500 | $2,500 | $5,000 | $20,000 |
|---|---|---|---|---|---|
| ORB Sharpe | 0.21 | 0.38 | 0.58 | 0.74 | 0.80 |
| QQQ noise Sharpe | 0.74 | | | 1.38 | |
| Daily book Sharpe | | | 0.85 | 0.91 | |

The daily book barely cares about its size (few trades); the intraday sleeves care a lot.

## Follow-up (not pre-registered): overlay on the same capital

All sleeves trade one $5k margin account. Daily returns add; overnight exposure is only the
daily book's (≤ 1x):

| Overlay | CAGR | Sharpe | Max DD | Sharpe 2021–23 | Sharpe 2024–26 |
|---|---|---|---|---|---|
| Daily book only | 7.3% | 0.91 | −10.3% | 0.10 | 1.39 |
| Daily + ORB | 20.2% | 1.00 | −18.5% | 0.52 | 1.32 |
| Daily + ORB candidate | 25.2% | 1.22 | −17.7% | 0.61 | 1.61 |
| **Daily + QQQ noise** | 28.3% | **1.69** | −10.1% | 1.62 | 1.75 |
| Daily + ORB + QQQ noise | 43.7% | 1.61 | −14.3% | 1.37 | 1.77 |

**The 4x intraday cap.** Gross exposure as a multiple of equity (mean / 95th percentile / max):

| Sleeve | Mean | 95th pct | Max |
|---|---|---|---|
| Daily book | up to 1.00 | 1.00 | 1.00 |
| ORB | 0.24 | 0.51 | 1.22 |
| QQQ noise | 1.78 | 3.11 | 4.00 |

- **Daily + ORB fits comfortably:** about 1.5x on busy days.
- **Daily + QQQ noise exceeds 4x on its busiest days** (up to 5x), and all three reach 4.6x
  at the 95th percentile. Those rows assume leverage IBKR won't allow. **QQQ noise would have
  to run at a lower vol target** (roughly half, e.g. 1% instead of 2%). That would roughly
  halve its contribution but keep its Sharpe.

## Caveats

- **Not pre-registered:** the overlay idea came from the sub-account result, and the ORB
  candidate was picked after earlier tests on the same data.
- **QQQ noise was chosen partly because SPY failed** (the other agent's own warning), and the
  noise-area paper's sample overlaps our first ~2.5 years.
- **About 4.9 years of intraday data**; the daily book's 2021–23 was weak (Sharpe 0.10), which
  flatters every "add a sleeve" comparison in that half.
- Returns are added as if the sleeves never interact; in practice margin calls and order
  queueing could.

## What to do with this

1. **Paper-trade the overlay structure, not the backtest numbers.** Suggested shape: daily book
   (core) + ORB baseline overlay + QQQ noise overlay at a reduced vol target, kept under 4x
   intraday.
2. **This needs a margin account** (Reg T $2,000 minimum) with intraday leverage enabled.
3. **Validate the ORB candidate and the QQQ noise sleeve forward** before sizing them up.

## Sources

- Zarattini, Aziz & Barbon (2024), Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172
- Zarattini, Barbon & Aziz (2024), A Profitable Day Trading Strategy for the U.S. Equity Market. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
