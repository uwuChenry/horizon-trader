# ORB on Stocks in Play: the paper (2026-09-25)

What [Zarattini, Barbon & Aziz (2024)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284) claim, the exact rules, and what the paper leaves out. **Our replication and every experiment are logged in `orb_experiments.md`**. This note is the paper's side only, so the two don't repeat each other.

**Bottom line**
- The paper claims a Sharpe of 2.81 from a 5-minute opening range breakout, traded only on "Stocks in Play": the stocks with the most unusual opening volume that day.
- The signal is real: our replication confirms it before costs, before and after publication.
- But the paper models commissions only. The edge is a few cents per share, and measured slippage takes most of it.
- Our best realistic version is about Sharpe 0.7 at $5k, not 2.8.

## The claim

2016-2023, 7,000+ US stocks, $0.0035/share commission, **no slippage**:

| | Total return | Annual return | Sharpe | Alpha | Beta | Max DD |
|---|---|---|---|---|---|---|
| **5-min ORB, Stocks in Play (top 20)** | 1,637% | 41.6% | **2.81** | 35.8% | ~0 | 12% |
| 5-min ORB, all stocks (no relative-volume filter) | 29% | 3.2% | 0.48 | 3.3% | | |

The Stocks-in-Play filter is the whole strategy: without it the ORB barely works.

## The rules

Implemented as the paper defaults in `intraday/orb.py`:

| Step | Rule |
|---|---|
| Universe | Open > $5, 14-day average volume >= 1M shares, 14-day ATR > $0.50 |
| Stocks in Play | Relative volume = first-5-minute volume / its 14-day average. Require >= 1 and keep the **top 20** each day |
| Direction | Long if the first 5-minute candle closed up, short if down, skip if flat |
| Entry | Stop order at the opening-range high (long) or low (short) |
| Stop | 10% of the 14-day ATR from the entry |
| Exit | At the stop, otherwise at the close. Always flat overnight |
| Sizing | A stop-out loses 1% of equity, at most 4x leverage in total |

## Opening range length

This is the paper's own comparison; it chose the best row:

| Range | Total return | Annual return | Sharpe | Max DD |
|---|---|---|---|---|
| **5 min** | 1,637% | 41.6% | 2.81 | 12% |
| 15 min | 272% | 17.4% | 1.43 | 11% |
| 30 min | 21% | 2.3% | 0.21 | 35% |
| 60 min | 39% | 4.1% | 0.40 | 21% |

- The edge fades quickly as the window lengthens. It lives in the first minutes after the open, which is exactly when spreads are widest and fast breakouts are hardest to fill.
- Choosing 5 minutes out of four windows tested on the same data is a small in-sample selection. The drop-off is steep enough that it doesn't change the picture.

## What the paper leaves out

| Omission | Why it matters | What we found (details in `orb_experiments.md`) |
|---|---|---|
| **Slippage** | Stop orders chase a fast move and fill worse than the trigger | Measured on 1-second bars: 4.5c/share on entry at the realistic estimate. At $25k top-20, Sharpe goes from 2.1 (0c) to 0.39 (1c) to wiped out (2c) |
| **What happens inside the entry minute** | With a 0.1 ATR stop (median 14c), the stop often sits inside the entry bar | 52% of trades are ambiguous on minute bars. Avg R ranges from -0.29 to +0.27 depending on the assumption. A 1 ATR stop removes this |
| **Per-order minimums** | At $5k, $1 per order (Fixed) or $0.35 (Tiered) is large next to a cents-per-share edge | Tiered beats Fixed at $5k |
| **Short-borrow cost and availability** | Hot stocks can be hard to borrow | Not modeled |
| **Short-sale restriction** | After a 10% drop, shorts can only be entered on an uptick | Flagged, not excluded |
| **Concentration** | A few all-day runners make the money | The best 5% of trades carry 300% of total R. Capping winners (breakeven or trailing stops) destroys the edge |

## Independent checks

- [QuantConnect's replication](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/) gets Sharpe 2.4 for 2016 on a 1,000-stock universe. It uses similar cost assumptions, so it confirms the signal but not the tradeability.
- **Ours** (Massive data, Oct 2021 to Sep 2026, delisted names included):
  - The signal replicates before costs and rises with relative volume every year, including after publication.
  - The best realistic setup: top-1 stock, 1 ATR stop, stop-limit entry at the trigger, $5k on IBKR Tiered. That gives **12.2% CAGR, Sharpe 0.72, -22% max drawdown**, nearly uncorrelated with SPY.
  - Full log in `orb_experiments.md`.

## Related

- [Zarattini & Aziz (2023), "Can Day Trading Really Be Profitable?"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622): a 5-minute ORB on QQQ alone, 2016-2023, reporting a Sharpe of 1.13. It assumes $0.0005/share commission and no slippage, so it has the same weakness.
- The same authors' SPY noise-area momentum paper is replicated in `strategy_survey.md`. It also held up well inside its own sample and faded after publication on SPY.

## Sources

- Zarattini, Barbon & Aziz (2024), A Profitable Day Trading Strategy For The U.S. Equity Market. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
- Concretum Group, paper summary. https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/
- QuantConnect, Opening Range Breakout for Stocks in Play (replication). https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/
- DanFin, Opening Range Breakout Research: What Two Day-Trading Papers Actually Found. https://danfin.net/opening-range-breakout-research
- Zarattini & Aziz (2023), Can Day Trading Really Be Profitable? https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622
