# Gold vs the dollar: is the inverse relationship tradeable? (2026-09-25)

An idea from an online post: gold and the dollar index (DXY) move inversely, so when one moves and the other hasn't followed yet, trade the catch-up.

**Bottom line**
- **The relationship is real and stable.** GLD's daily returns correlate with the dollar at -0.2 to -0.65 in *every* year from 2007 to 2026, including 2022-2026, when many commentators said it "broke".
- **It is not tradeable at daily-to-monthly horizons.** Five pre-registered tests found no lead from the dollar to gold, and no reliable closing of gaps. None cleared the pass rule.
- The two prices adjust *together, within the same day*. By the time a daily bar shows the gap, it's already priced.

## What the research says

- **The link exists but its strength drifts.** [Capie, Mills & Wood (2005)](https://econpapers.repec.org/RePEc:eee:intfin:v:15:y:2005:i:4:p:343-352) used 30 years of weekly data and found a negative relationship between gold and the dollar, but it shifts over time, "highly dependent on unpredictable political attitudes and events".
- **Gold acts partly like a currency.** [Pukthuanthong & Roll (2011)](https://ideas.repec.org/a/eee/jbfina/v35y2011i8p2070-2083.html): when the dollar depreciates, the dollar price of gold rises, and similar links hold for the euro, pound and yen.
- **It's a hedge, including in extremes.** [Reboredo (2013)](https://ideas.repec.org/a/eee/jbfina/v37y2013i8p2665-2676.html) finds positive dependence between gold and dollar *depreciation*, including in extreme moves, so gold works as a dollar hedge and safe haven.
- **What the papers don't claim:** none of them report that the dollar *predicts* gold. They're about same-period co-movement, which is useful for hedging and diversification but not for timing.
- **The "breakdown" is about trends, not daily moves.** In 2024 the dollar rose ~7% and gold ~27%, driven by record central-bank buying of more than 1,000 tonnes a year in 2022-2024 ([Fed IFDP 1420](https://www.federalreserve.gov/econres/ifdp/files/ifdp1420.pdf); [Amundi](https://research-center.amundi.com/article/gold-beyond-records)). Other forces can drive the *level* of gold for years while day-to-day moves stay inversely linked. Our data shows exactly this.
- **The dollar isn't the main valuation driver.** [Erb & Harvey (2013), "The Golden Dilemma"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2078535): gold is an unreliable inflation hedge over practical horizons. When its real price is high, later returns have tended to be below average, but central-bank demand can override that.

## The tests (`uv run python -m horizon_trader.macro.gold_dollar`)

**Setup**
- Data: GLD versus UUP (a long-dollar-index ETF), daily, 2007-03 to 2026-09.
- **Why UUP rather than DXY itself:** DXY settles at 17:00 ET, an hour after GLD's close. That would let "DXY today" contain news GLD only reacts to tomorrow: a fake lead.
- The signal is known at the close of day t. The forward return runs from the open of t+1.
- All five tests and the pass rule were written in the code's docstring before the first run.
- Pass rule: Newey-West t >= 2 in the claimed direction over the full sample, **and** a positive IC in both halves.

| Test | What it bets on | IC | t | IC 2007-16 | IC 2017-26 | Pass |
|---|---|---|---|---|---|---|
| T1 lead 1d | Dollar fell today, so gold rises tomorrow | -0.013 | -0.71 | -0.021 | 0.000 | no |
| T2 lead 5d | Dollar fell this week, so gold rises next week | -0.031 | -1.18 | -0.005 | -0.072 | no |
| T3 gap 5d | Gold ran ahead of what the dollar implied this week, so it gives some back | +0.040 | 1.37 | +0.006 | +0.090 | no |
| T4 gap 20d | Same over a month | +0.033 | 0.67 | +0.072 | -0.017 | no |
| T5 level gap | Gold's price is far from its fitted dollar relationship, so it reverts (monthly) | +0.045 | 0.87 | +0.122 | -0.011 | no |

- The "dollar leads gold" idea (T1, T2) has the wrong sign, and it's small.
- The gap-closing idea (T3 to T5) has the right sign but isn't significant. The closest, T3, is t = 1.4 with nearly all of it from 2017 onward.
- With five tests, even one t of 2 would have been weak evidence.

**Trading versions** (long GLD when the signal is positive, else flat; $5k, IBKR Tiered, 2009 to 2026):

| Run | In market | CAGR | Sharpe | Max DD | Commissions |
|---|---|---|---|---|---|
| GLD buy & hold | 100% | 8.5% | 0.57 | -46% | $2 |
| T1 lead 1d | 47% | -3.3% | -0.23 | -57% | $1,056 |
| T2 lead 5d | 48% | -2.0% | -0.10 | -61% | $221 |
| T3 gap 5d | 46% | -0.8% | -0.01 | -55% | $193 |
| T4 gap 20d | 40% | 3.7% | 0.43 | -29% | $63 |
| T5 level gap | 47% | 5.9% | 0.59 | -35% | $37 |

- The random control (same time in the market, random timing) has a median Sharpe of 0.02-0.36. That's the bar a real signal must clear.
- T5 matches buy-and-hold's Sharpe while holding gold half the time. But its IC is insignificant and negative after 2016, so this is most likely luck plus lower exposure, not skill.
- Nothing here is worth trading.

## Why it doesn't work, and what would

- Gold and the dollar are among the most liquid markets in the world. Futures and FX desks close the gap between them in seconds to minutes. A daily or weekly bar only ever sees the relationship *after* it has been arbitraged.
- A tradeable version would have to be intraday lead-lag between gold futures and dollar futures, measured in seconds. That's HFT territory and out of scope here.
- **What the relationship is good for:** diversification and risk, not return timing.
  - Gold tends to rise when the dollar falls, so it can hedge a portfolio's dollar exposure.
  - Gold has near-zero correlation with the equity sleeves.
  - If you want gold in the book, a plain strategic allocation, or gold inside the existing momentum/trend rotation, is the evidence-based use.

## Sources

- Capie, Mills & Wood (2005), Gold as a hedge against the dollar, J. Int. Financial Markets. https://econpapers.repec.org/RePEc:eee:intfin:v:15:y:2005:i:4:p:343-352
- Pukthuanthong & Roll (2011), Gold and the Dollar (and the Euro, Pound, and Yen), J. Banking & Finance. https://ideas.repec.org/a/eee/jbfina/v35y2011i8p2070-2083.html
- Reboredo (2013), Is gold a safe haven or a hedge for the US dollar?, J. Banking & Finance. https://ideas.repec.org/a/eee/jbfina/v37y2013i8p2665-2676.html
- Erb & Harvey (2013), The Golden Dilemma, Financial Analysts Journal. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2078535
- Federal Reserve IFDP 1420, De-Dollarization? Diversification? Exploring Central Bank Gold Purchases. https://www.federalreserve.gov/econres/ifdp/files/ifdp1420.pdf
- Amundi Research, Gold Beyond Records 2025. https://research-center.amundi.com/article/gold-beyond-records
