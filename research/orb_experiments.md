# ORB experiments: what we tested and what we learned

Opening Range Breakout on "Stocks in Play", replicated from Zarattini, Barbon & Aziz (2024),
[A Profitable Day Trading Strategy for the U.S. Equity Market](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284)
(SSRN 4729284). Log started 2026-09-25. Code: `src/horizon_trader/intraday/`. Saved runs are on
the **Backtests** page (names start with "ORB").

## Where we are (TL;DR)

- **The signal is real before costs.** Stocks with unusual opening volume keep running in the
  direction of their first 5-minute candle. Profit per trade rises steadily with relative
  volume, in every year from 2021 to 2026, including after the paper was published.
- **Execution decides everything.** With the paper's tight stop (0.1 ATR), minute bars can't
  tell whether you'd have been stopped out, and slippage eats most of the edge. A **1 ATR stop**
  is the robust choice.
- **Best realistic setup so far:** top-1 stock per day, 1 ATR stop, stop-limit entry at the
  trigger price, 1% risk per trade, $5k on IBKR Pro Tiered → **12.0% CAGR, Sharpe 0.70, max
  drawdown −22%** (Oct 2021 – Sep 2026). Adding "no entries after 10:30": **14.2%, Sharpe 0.82**. SPY over the same period: ~11%, Sharpe ~0.7, but ORB
  is nearly uncorrelated with the market (beta 0.02).
- **What helped (pre-registered test):** no entries after 10:00–11:00, and requiring higher
  relative volume. **What hurt:** trading with SPY's direction, breakeven stops, trailing stops.
  No idea raised the win rate (~44%).
- **Parameter grid (see [ORB parameter grid](orb_parameter_grid.md)):** 480 configurations ×
  4 slippage scenarios × 2 account sizes. Picking the best on 2021–23 lost to the plain
  baseline on 2024–26 in 8 of 8 cases; nothing survives a correction for 480 tries. Profit
  targets and tight stops always hurt; relative volume ≥ 12 plus no entries after 10:30 is
  the one candidate worth validating (Sharpe 0.94 full period, but chosen after the fact).
- **Round-2 filters and large caps (Experiments 8–10):** a large-cap filter, an overnight-gap
  catalyst and a volatility-regime filter all failed the pre-registered test. Large caps are
  cheaper per share in percent but lose the edge.
- **ORB on ETFs failed** (see [ETF ORB](etf_orb.md)): slippage is small there, but so is
  the edge in 2021–2026.
- **Combining matters more than tuning** (see [Combining strategies](portfolio_mix.md)): overlaid
  on the daily book in one margin account, ORB lifts the portfolio's Sharpe from 0.91 to 1.00
  (not pre-registered).
- **Next:** confirm on data none of this has touched (2016–2021), and paper trade on IBKR.
  Nothing here has been traded with real money.

## Setup

| | |
|---|---|
| Data | Massive (ex-Polygon) flat files, Starter plan: 1-minute and daily bars, all US stocks incl. delisted, Oct 2021 – Sep 2026. 1-second bars from Massive's REST API for fills. |
| Universe | US common stocks only (no ETFs, warrants, preferreds), split-adjusted via Massive's split history. |
| Timing | Signals use only information available at 9:35 on day t (tested for lookahead). |
| Costs | IBKR Pro Tiered: $0.0035/share, $0.35 minimum, + clearing $0.0002/share, + **assumed** $0.003/share exchange fee, + SEC/FINRA fees on sells. |
| Margin | IBKR charges interest on **end-of-day settled** cash, so same-day leverage (all ORB trades) costs no interest; same-day shorts don't settle, so no borrow fee is expected. |

**The paper's rules** (our baseline replication): open > $5, 14-day average volume ≥ 1M, 14-day
ATR > $0.50; relative volume (first 5 minutes vs its 14-day average) ≥ 1; top 20 by relative
volume; long if the first candle closed up, short if down; stop order at the candle's high/low;
stop 10% of ATR; exit at the close; size so a stop-out loses 1% of equity, max 4x leverage.

## Experiment 1: replication (top 20, paper's 0.1 ATR stop)

Average profit per trade in R (multiples of the stop distance), before costs. It depends
entirely on what happened *inside* the entry minute, which minute bars can't show:

| How the entry minute is treated | Avg R | $25k, paper's costs: CAGR / Sharpe |
|---|---|---|
| Any stop touch counts ("cons") | −0.29 | −69% / −4.7 (wiped out) |
| Guess from bar direction ("path", default) | +0.27 | 133% / 2.43 |
| Stop ignored in that minute ("opt") | +0.18 | 71% / 1.55 |

- 52% of trades touch the 14¢ median stop inside the entry minute.
- Profit is extremely concentrated: the best 5% of trades carry 300% of total R.
- Avg R by relative volume (path): 2–3x +0.10, 3–5x +0.19, 5–10x +0.28, 10–30x +0.45, 30x+
  +0.55. **Positive in every year 2021–2026.**
- With realistic costs at $25k top-20, IBKR Fixed: 0¢ slippage Sharpe 2.1, **1¢ 0.39, 2¢
  wiped out**. The paper's result needs perfect fills.

## Experiment 2: stop width (robustness check, flat 1¢ slippage, IBKR Fixed)

| Stop (ATR) | 0.05 | 0.1 | 0.2 | 0.35 | 0.5 | 1.0 |
|---|---|---|---|---|---|---|
| Median stop | 7¢ | 14¢ | 28¢ | 50¢ | 71¢ | $1.42 |
| Entry minute ambiguous | 77% | 52% | 22% | 7% | 2% | 0.2% |
| Trades stopped out | 91% | 86% | 75% | 60% | 47% | 20% |
| $25k top-20, 1¢: Sharpe | 0.72 | 0.50 | −2.36 | −0.12 | −0.36 | 0.09 |
| $5k top-2, 1¢: CAGR | 190% | 105% | 45% | 27% | 28% | 15% |
| $5k top-2, 1¢: Sharpe | 1.24 | 1.08 | 0.82 | 0.71 | 0.81 | 0.71 |
| $5k top-2, 1¢: max DD | −67% | −69% | −53% | −55% | −45% | −30% |

**Lesson:** the stop width sets *leverage* (how many shares 1% risk buys), not the edge. Edge
per share before costs barely changes with the stop (top-2: 10–16¢; top-20: 4–7¢). Tight stops
look great only because they multiply a small edge with near-perfect fills assumed.

## Experiment 3: measured slippage (1-second bars)

1,980 top-2 entries and 574 stop-outs, 1 ATR stop. Cents per share worse than the backtest
assumed (the median is ~0, but the tail is fat):

| Fill estimate | Entry: mean / median / worst 10% | Stop-out: mean |
|---|---|---|
| Average price of the trigger second (optimistic) | 1.7¢ / 0¢ / 4.8¢+ | 1.4¢ |
| **First trade one second later (realistic)** | **4.5¢ / 0¢ / 12.5¢+** | **4.0¢** |
| Worst trade in the trigger second (pessimistic) | 6.8¢ / 2¢ / 18¢+ | 6.8¢ |

These are floors: second bars show trades, not the bid/ask. Slippage is **not** a size
problem. It's the cost of chasing a fast breakout, the same per share for 1 share or 10,000.

## Experiment 4: order type, account size, commission plan

Top-1, 1 ATR stop, measured fills. Stop-limit fills assumed at the limit price (worst case):

| Setup | CAGR | Sharpe |
|---|---|---|
| $5k Fixed, stop-market entry | 6.3% | 0.42 |
| $5k Tiered, stop-market entry | 10.3% | 0.62 |
| $5k Fixed, stop-limit at trigger | 8.2% | 0.52 |
| **$5k Tiered, stop-limit at trigger (baseline)** | **12.2%** | **0.72** |
| $20k Fixed, stop-limit at trigger | 14.0% | 0.79 |

- A stop-limit at the trigger price fills 97% of trades; the 3% it misses run away
  immediately and average +1.4R (you miss some of the best trades, but save slippage on all).
- Wider limits (+5¢, +10¢) were worse. Tiered beats Fixed at $5k (the $0.35 vs $1 minimum).
- IBKR Lite ($0 commission) is US-residents only, so not available to us.

## Experiment 5: pre-registered ideas (`orb_ideas.py`)

Baseline as in Experiment 4, with one correction: from here on, a stop hit inside the fill
minute is checked on the **1-second bars after the fill** instead of the whole minute (whose
range includes prices from before the fill). That moves the baseline from 0.72 to 0.70. 14 variants, ideas and pass rule written down before running.
**Pass = beats the baseline's Sharpe in both 2021–23 and 2024–26**, each with fresh capital; a
family passes only if ≥2 settings pass, including the middle one.

| Idea | Sharpe | CAGR | Max DD | Trades/yr | Win rate | Profit factor | Sharpe 21–23 | Sharpe 24–26 | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **Baseline** | 0.70 | 12.0% | −21.7% | 199 | 44.3% | 1.15 | 0.50 | 0.82 | — |
| Trade with SPY's direction | 0.40 | 5.1% | −22.0% | 195 | 44.6% | 1.06 | 0.27 | 0.48 | fail |
| **No entries after 10:00** | **0.84** | **14.4%** | −19.3% | 170 | 43.8% | 1.20 | 0.54 | 1.01 | pass |
| **No entries after 10:30** | **0.82** | **14.2%** | −19.7% | 180 | 44.0% | 1.19 | 0.52 | 1.01 | pass |
| **No entries after 11:00** | **0.82** | **14.2%** | −20.3% | 185 | 44.3% | 1.18 | 0.55 | 0.99 | pass |
| Relative volume ≥ 3 | 0.70 | 12.0% | −21.7% | 199 | 44.3% | 1.15 | 0.50 | 0.82 | no change |
| Relative volume ≥ 5 | 0.71 | 12.1% | −21.6% | 198 | 44.3% | 1.15 | 0.51 | 0.82 | pass |
| Relative volume ≥ 8 | 0.76 | 13.1% | −21.8% | 193 | 44.3% | 1.16 | 0.61 | 0.85 | pass |
| **Relative volume ≥ 12** | **0.86** | **15.0%** | −21.7% | 176 | 44.5% | 1.20 | 0.61 | 1.01 | pass |
| Breakeven stop at +0.5R | −0.15 | −3.5% | −33.4% | 199 | 27.7% | 0.94 | −0.36 | 0.00 | fail |
| Breakeven stop at +1R | 0.33 | 4.3% | −24.2% | 199 | 38.8% | 1.06 | 0.27 | 0.36 | fail |
| Breakeven stop at +2R | 0.67 | 11.2% | −22.7% | 199 | 43.8% | 1.14 | 0.56 | 0.74 | fail |
| Trailing stop 0.5R | −1.75 | −12.1% | −49.8% | 199 | 37.2% | 0.72 | −1.74 | −1.61 | fail |
| Trailing stop 1R | −0.79 | −9.7% | −46.7% | 199 | 39.6% | 0.86 | −0.39 | −1.09 | fail |
| Trailing stop 2R | 0.43 | 5.6% | −22.1% | 199 | 44.7% | 1.07 | 0.53 | 0.31 | fail |

Family verdicts: **entry cutoff PASS, relative volume PASS**; market direction, breakeven and
trailing stops fail.

- **Why the exits failed:** the profit comes from a few all-day runners. Breakeven and trailing
  stops cut them short, and lower the win rate too, because breakeven exits lose the costs.
- **Caution:** over ~2.5-year halves the standard error of Sharpe is about ±0.6, so the
  +0.1–0.15 improvements are within noise. The pass rule removes obvious flukes; it can't prove
  an idea is real. 14 variants were tested on the same data.

## Experiment 6: risk per trade (baseline, $5k Tiered)

With a 1 ATR stop and 1% risk, the average position is only 0.24x the account. Risk per trade
is the lever for CAGR; it barely changes Sharpe:

| Risk per trade | Avg position | CAGR | Sharpe | Max DD | Worst day |
|---|---|---|---|---|---|
| 0.5% | 0.12x | 4.4% | 0.52 | −12% | −1.5% |
| **1% (current)** | 0.24x | 12.0% | 0.70 | −22% | −2.9% |
| 2% | 0.49x | 23.9% | 0.76 | −39% | −5.9% |
| 3% | 0.73x | 32.1% | 0.76 | −53% | −8.8% |
| 5% | 1.22x | 38.4% | 0.77 | −73% | −14.6% |

The worst day is one trade: GLTO on 2025-10-07. It opened above its breakout level, so the
stop-limit buy rested below the market. Eight seconds later the stock fell $1.77 **within one
second**: the order filled on the way down and the stop was blown through, a −2.8R loss.
Resting limit orders tend to fill at the worst moment; stops don't cap losses in a crash.

**CAGR is chosen, Sharpe is earned.** Returns grow slower than risk (3% → 5% adds 7 points of
CAGR and 20 points of drawdown). 1–2% is sensible.

## Experiment 7: 0.5 ATR vs 1 ATR stop, at 1% and 2% risk

Same setup as Experiment 5 (top-1, stop-limit entry, measured stop-out slippage, $5k Tiered):

| Stop | Idea | Risk | CAGR | Sharpe | Max DD | Worst day | Win rate | Stopped out | Avg position | Sharpe 21–23 | Sharpe 24–26 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.5 ATR | baseline | 1% | 9.6% | 0.44 | −48% | −5.8% | 34% | 56% | 0.49x | 0.22 | 0.57 |
| 0.5 ATR | baseline | 2% | 11.6% | 0.46 | −75% | −11.7% | 34% | 56% | 0.98x | 0.24 | 0.59 |
| 0.5 ATR | by 10:30 | 1% | 12.5% | 0.52 | −46% | −5.9% | 33% | 58% | 0.48x | 0.20 | 0.72 |
| 0.5 ATR | by 10:30 | 2% | 17.4% | 0.54 | −74% | −11.7% | 33% | 58% | 0.97x | 0.21 | 0.73 |
| **1 ATR** | baseline | 1% | 12.0% | 0.70 | −22% | −2.9% | 44% | 32% | 0.24x | 0.50 | 0.82 |
| **1 ATR** | baseline | 2% | 23.9% | 0.76 | −39% | −5.9% | 45% | 32% | 0.49x | 0.57 | 0.87 |
| **1 ATR** | by 10:30 | 1% | 14.2% | 0.82 | −20% | −2.9% | 44% | 33% | 0.24x | 0.52 | 1.01 |
| **1 ATR** | by 10:30 | 2% | 28.5% | 0.86 | −36% | −5.9% | 45% | 33% | 0.48x | 0.57 | 1.05 |

**The 1 ATR stop wins everywhere.** At 0.5 ATR the position is twice as big for the same risk,
but 56% of trades get stopped out (vs 32%): many stop-outs are noise that would have
recovered, and each one pays slippage. The edge per share before costs falls from ~21¢ to
~17¢. Twice the leverage on a weaker edge gives a lower Sharpe and 2x deeper drawdowns.
**Best row: 1 ATR, no entries after 10:30, 2% risk: 28.5% CAGR, Sharpe 0.86, −36% max DD.**


## Experiment 8: large-cap filter (`orb_largecap.py`)

Pre-registered: keep only stocks whose 14-day average dollar volume is at least $50M / $100M
/ $250M a day (a point-in-time large-cap proxy), applied before the top-50 cut. Each filter
got **its own measured slippage**, since the hypothesis was that large caps are cheaper to
trade.

| Filter | Median price | Entry slippage | Stop-out slippage | Entry slippage (bps) | Sharpe | CAGR | Sharpe 2021–23 | Sharpe 2024–26 | Pass |
|---|---|---|---|---|---|---|---|---|---|
| **None (baseline)** | $28 | 4.1¢ | 4.2¢ | 14.3 | 0.70 | 11.8% | 0.49 | 0.81 | — |
| ≥ $50M/day | $51 | 5.4¢ | 4.3¢ | 8.8 | 0.18 | 1.6% | 0.39 | 0.03 | no |
| ≥ $100M/day | $74 | 6.5¢ | 4.8¢ | 7.5 | −0.03 | −1.4% | 0.71 | −0.59 | no |
| ≥ $250M/day | $120 | 7.9¢ | 4.8¢ | 5.3 | 0.11 | 0.5% | −0.18 | 0.25 | no |

(Stop-limit entry, $5k Tiered. Stop-market entries tell the same story.) **Larger stocks
cost less in percentage terms (14 → 5 bps) but more cents per share, and the edge shrinks
faster than the cost.** The ORB edge lives in the smaller, more volatile names.

## Experiments 9–10: round-2 ideas, gap catalyst and volatility regime (`orb_ideas.py --round 2`)

Pre-registered before running. The overnight gap is a free proxy for a news or earnings
catalyst, since earnings dates need a paid data add-on. Same baseline and pass rule as
Experiment 5.

| Idea | Sharpe | CAGR | Max DD | Trades/yr | Profit factor | Sharpe 2021–23 | Sharpe 2024–26 | Verdict |
|---|---|---|---|---|---|---|---|---|
| **Baseline** | 0.70 | 12.0% | −21.7% | 199 | 1.15 | 0.50 | 0.82 | — |
| Gap ≥ 2% | 0.83 | 14.8% | −24.4% | 200 | 1.16 | 1.01 | 0.67 | fail |
| Gap ≥ 4% | 0.78 | 13.6% | −23.7% | 196 | 1.15 | 0.59 | 0.90 | passes alone |
| Gap ≥ 8% | 0.72 | 12.3% | −27.3% | 188 | 1.16 | 0.01 | 1.15 | fail |
| Gap in the direction of the first candle | −0.15 | −3.7% | −34.7% | 190 | 0.95 | −0.57 | 0.13 | fail |
| High-volatility days only | 0.70 | 9.0% | −12.7% | 102 | 1.24 | 0.62 | 0.74 | fail |
| Low-volatility days only (control) | 0.25 | 2.4% | −17.7% | 97 | 1.06 | 0.10 | 0.38 | control |

Family verdicts: **all fail** (a family needs two passing settings including the middle one).

- **The gap filter is noise:** the 2%, 4% and 8% settings swap which half they help.
- **A gap in the same direction as the first candle is clearly harmful.** The opposite
  (fading the gap) would be a new, unregistered idea. Noted here, not tested.
- **Volatility regime:** trading only high-volatility days keeps the same Sharpe with half
  the trades and **half the drawdown** (profit factor 1.24 vs 1.15), and the low-vol control
  is much worse. That's consistent with Lundström (2017), but it didn't beat the baseline in
  2024–26, so it fails.

## Lessons (apply to future strategies too)

1. **Always test with measured fills.** Zero-slippage intraday backtests are fiction; online
   claims like "41% CAGR without fees" say almost nothing.
2. **Tight stops are leverage in disguise.** Judge an intraday edge per share after costs.
3. **Minute bars can't resolve stops close to the entry.** Use second bars, or stops wide
   enough that the question doesn't arise.
4. **Don't cap the winners of a fat-tailed strategy.** Profit targets, breakeven and trailing
   stops all destroyed this one.
5. **Pre-register ideas, count variants, require both halves**, and expect in-sample
   improvements to shrink.
6. **Win rate is not the target.** Expectancy and Sharpe after costs are.

## Open questions and next steps

Not pursued (owner's decision, 2026-09-25): micro Nasdaq futures (MNQ), and LLM or
discretionary news judgement (forward-test only; can't be backtested honestly).

1. **Untouched data:** one month of Massive Developer ($79) adds 2016–2021 minute bars. Run the
   baseline, "no entries after 10:30" and "relative volume ≥ 8" unchanged there.
2. **Paper trading** on IBKR once the account is ready: measures real slippage and the Tiered
   exchange fees (currently assumed).
3. **Combine ORB with the daily sleeves:** near-zero correlation should raise the portfolio's
   Sharpe. Not yet measured.
4. **Not modeled:** short borrow availability for hot stocks, short-sale-restricted days,
   US dividend withholding (daily sleeves only).

## Reproduce

```bash
uv run python -m horizon_trader.intraday.orb [--stop-atr 1.0] [--save]    # replication report
uv run python -m horizon_trader.intraday.orb --stops 0.05,0.1,0.2,0.35,0.5,1.0
uv run python -m horizon_trader.intraday.slippage --top 2 --stop 1.0 [--compare] [--save]
uv run python -m horizon_trader.intraday.orb_ideas [--save]               # Experiment 5
uv run python -m horizon_trader.intraday.orb_ideas --round 2 [--save]     # Experiments 9-10
uv run python -m horizon_trader.intraday.orb_largecap [--save]            # Experiment 8
uv run python -m horizon_trader.intraday.etf_orb [--save]                 # ETF ORB
uv run python -m horizon_trader.backtest.mix [--save]                     # combining strategies
```

## Sources

- IBKR margin rates: first $100k at benchmark + 1.5% (about 5.1–5.4% in 2026); interest only on end-of-day settled debit balances.

- Zarattini, Barbon & Aziz (2024), A Profitable Day Trading Strategy for the U.S. Equity Market. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
- Massive flat files (minute aggregates). https://massive.com/docs/flat-files/stocks/minute-aggregates
- Massive market data terms of service. https://massive.com/legal/market-data-terms-of-service
- IBKR stock commissions (Fixed and Tiered). https://www.interactivebrokers.com/en/pricing/commissions-stocks.php
- IBKR margin rates. https://www.interactivebrokers.com/en/trading/margin-rates.php
- IBKR margin interest calculation (end-of-day settled balances). https://www.interactivebrokers.com/en/trading/margin-calculation-details.php
- FINRA Regulatory Notice 26-10 (PDT rule replaced). https://www.finra.org/rules-guidance/notices/26-10
