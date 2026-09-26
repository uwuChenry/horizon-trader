# Catching the next Nvidia: momentum among the 200 largest companies

Run 2026-09-26 with `uv run python -m horizon_trader.backtest.winners`. Code:
`src/horizon_trader/backtest/winners.py`. Follows [Owning the biggest companies](megacap.md).

> **Corrected 2026-09-26.** The first run had a data error: two reused tickers (see
> [Data fix](#data-fix-reused-tickers)) produced fake momentum. All numbers below are after the fix.
> The fix lowered the top-10 result from 48.9% to 45.4% a year and its Sharpe from 1.22 to 1.14.

## Answer first

- **Momentum did catch most of the period's giant winners, but late.** It owned Nvidia for 22 of
  47 months, *after* it had already doubled; it bought many others only after gains of 400–2,800%.
  You don't find the next Nvidia early; you join it once it's clearly winning.
- **Returns were very high:** top 10 by 12-month momentum made **45.4% a year at $5k after
  costs**, vs SPY 19.2% and QQQ 28.6% (Oct 2022 – Sep 2026).
- **But it's extra risk, not extra skill.** The portfolio moved 1.6x the market. SPY held at 1.6x
  leverage over the same days returned 31.2% at a **slightly better Sharpe** (1.22 vs 1.14), with
  a smaller drawdown (−29% vs −40%). Losing months were brutal: **−27% in July 2026**, and single
  picks fell 30–47% in a month.
- **The test is short and flattering:** under 4 years, starting near the October 2022 market
  bottom, in an AI-driven boom that rewarded exactly the stocks momentum buys. Momentum's
  famous weakness, sudden crashes when markets rebound sharply (Daniel & Moskowitz 2016), never
  happened here.
- **Survivorship nearly doubles the result.** The same rule on *today's* 200 largest companies
  shows **87% a year**. That's the kind of backtest that looks amazing and isn't real.

## The rules (pre-registered, 4 variants)

- **Universe:** each month-end, the 200 largest US companies by market cap *as of that date*
  (Massive point-in-time caps; delisted companies included; one share class per company).
- **Signal:** 12-1 momentum (the return from 12 months ago to 1 month ago, Jegadeesh & Titman)
  and the shorter 6-1 variant. The signal is unknown (skipped) when its window has more than 10
  trading days without a price (see the data fix).
- **Portfolio:** the top 10 or top 20 by momentum, equal weight. Formed at the month-end close,
  traded at the next open. Names that drop out are sold at the next month-end. In between, the
  target weight stays fixed and is checked daily: a position more than 2 percentage points from
  it is traded back (the rebalance band). That trimming and topping-up is most of the ~110
  trades a year. The no-cost rows let weights drift all month instead.
- **Costs:** the daily book's simulator: $5k, IBKR Pro Tiered, 5 bps slippage, 2% rebalance
  band, fractional shares.
- **Benchmark:** the same 200 companies at equal weight (the project's rule for stock picking),
  plus SPY and QQQ. Everything is price only (no dividends).

**See it day by day:** `uv run python -m horizon_trader.backtest.winners --save`, then the
dashboard's **Holdings** page. It has a date slider showing what the portfolio held at any
close (% of equity, entry date, move since bought), the month's ranking with what was bought
and sold, and a timeline of every holding period.

## Results

**12-1 momentum** (from Oct 2022; the first year of data is needed for the signal):

| Portfolio | CAGR, no costs | CAGR, $5k after costs | Sharpe ($5k) | Max drawdown | Beta to SPY | Costs over the period | Trades/yr |
|---|---|---|---|---|---|---|---|
| **Top 10** | 47.9% | **45.4%** | 1.14 | −40.2% | 1.61 | $160 | 109 |
| Top 20 | 29.2% | 29.6% | 0.94 | −36.0% | 1.46 | $217 | 154 |
| 200 largest, equal weight | 15.3% | | 1.06 (no costs) | −17.3% | 0.89 | | |
| SPY | 19.2% | | 1.22 | −19.0% | 1.00 | | |
| QQQ | 28.6% | | 1.32 | −22.9% | 1.27 | | |
| SPY at 1.61x leverage (same risk as top 10) | 31.2% | | 1.22 | −29.1% | 1.61 | | |
| SURVIVORSHIP: top 10 on *today's* 200 largest | 87.3% | | 1.70 | −39.6% | 1.72 | | |
| SURVIVORSHIP: *today's* 200 largest, equal weight | 28.7% | | 1.72 | −19.1% | 0.95 | | |

**6-1 momentum** (from Apr 2022, which includes part of the 2022 bear market):

| Portfolio | CAGR, no costs | CAGR, $5k after costs | Sharpe ($5k) | Max drawdown | Beta |
|---|---|---|---|---|---|
| **Top 10** | 35.0% | **32.9%** | 0.94 | −38.5% | 1.43 |
| Top 20 | 23.0% | 21.6% | 0.76 | −38.7% | 1.30 |
| 200 largest, equal weight | 12.3% | | 0.81 (no costs) | −17.3% | 0.91 |
| SPY | 15.2% | | 0.92 | −19.0% | 1.00 |
| QQQ | 21.6% | | 0.99 | −22.9% | 1.25 |
| SPY at 1.43x leverage | 21.3% | | 0.92 | −26.2% | 1.43 |

- **Against the equal-weight universe (the fair benchmark), momentum's top 10 wins** in both
  variants (Sharpe 1.14 vs 1.06, 0.94 vs 0.81). Top 20 doesn't beat it for 12-1 (0.94 vs 1.06).
- **Against simply leveraging the index, it loses slightly for 12-1 and ties for 6-1.**
- **Top 10 beat top 20** in both: the effect is concentrated in the very strongest names.
- **Costs were small** ($160–340 over 3.5–4.5 years at $5k) because only 10–20 positions turn over
  monthly.

## Did it catch the big winners?

The 15 biggest winners since Oct 2022 among companies that were ever in the top 200 (12-1, top 10):

| Company | Total rise | Months held (of 47) | First bought | Rise before first buy |
|---|---|---|---|---|
| SNDK | 3,508% | 7 | 2026-02 | 1,207% |
| CVNA | 2,272% | 3 | 2025-07 | 2,784% |
| PLTR | 2,091% | 21 | 2023-11 | 128% |
| MU | 1,897% | 12 | 2024-06 | 143% |
| APP | 1,742% | 13 | 2024-10 | 899% |
| STX | 1,724% | 11 | 2025-10 | 415% |
| VRT | 1,614% | 1 | 2026-03 | 1,651% |
| **NVDA** | 1,564% | **22** | **2023-04** | **106%** |
| RKLB | 1,346% | 0 | never | — |
| BE | 1,325% | 5 | 2026-04 | 1,414% |
| DELL | 1,296% | 12 | 2023-10 | 74% |
| FIX | 1,233% | 2 | 2026-02 | 1,059% |
| WDC | 1,210% | 11 | 2025-10 | 337% |
| LITE | 1,148% | 4 | 2026-04 | 1,112% |
| NBIS | 1,117% | 1 | 2026-06 | 1,281% |

"Total rise" runs from Oct 2022, or from when the company first appears. "Rise before first buy" is
measured from the same starting point. So a company whose rise mostly came *before* it entered
the top 200 shows a bigger number there.

- **14 of 15 were held at some point; only Rocket Lab was never bought.**
- **Nvidia, Palantir, Micron and Dell were caught relatively early** (after gains of 74–143%) and
  held for a year or more. Those are the trades that made the strategy.
- **Many others were only bought after enormous runs**, often after they grew into the top 200.
  Those late buys are where the worst months came from.

## The failures

Worst single-month outcomes for a pick (12-1, top 10):

| Month bought | Company | Next month |
|---|---|---|
| 2026-06 | SNDK | −46.6% |
| 2024-06 | CRWD | −39.5% |
| 2026-06 | INTC | −35.4% |
| 2026-06 | COHR | −33.4% |
| 2026-06 | BE | −32.0% |
| 2026-06 | NBIS | −31.1% |
| 2026-06 | MU | −28.7% |
| 2025-01 | TSLA | −27.6% |
| 2023-12 | COIN | −26.3% |
| 2025-01 | COIN | −26.0% |

**July 2026 (picks made at the end of June) was a momentum crash in miniature.** Six of the ten
worst picks came from that one month, and the portfolio lost 27%. Buying last year's biggest
winners means owning the most crowded, most volatile names when sentiment turns.

## Current picks, and is anything at the "caught early" stage?

The rule's picks at the latest formation (2026-08-31), with prices to 2026-09-24. The top 10 is
what the strategy holds now.

| Rank | Company | Mkt cap | 12-1 momentum | Months in top 10 before |
|---|---|---|---|---|
| 1 | SNDK Sandisk | $229B | +2,288% | 6 |
| 2 | MU Micron | $1,083B | +575% | 11 |
| 3 | WDC Western Digital | $162B | +564% | 10 |
| 4 | LITE Lumentum | $82B | +427% | 3 |
| 5 | STX Seagate | $188B | +397% | 10 |
| 6 | BE Bloom Energy | $61B | +276% | 4 |
| 7 | INTC Intel | $473B | +262% | 5 |
| 8 | AMAT Applied Materials | $364B | +207% | 1 |
| 9 | DELL Dell | $295B | +202% | 11 |
| 10 | AMD | $768B | +182% | 5 |
| 11–20 | LRCX, NBIS, MRVL, MRNA, WBD, VLO, HPE, KLAC, FTNT, GLW | | +101% to +182% | |

**For comparison, the early catches had this 12-1 momentum at their first buy:** Dell +73%,
Nvidia +47%, Micron +96%, Palantir +109%.

- **Nothing in today's top 10 matches that profile.** Every holding is up 180% to 2,300%, which is
  the "late" profile (memory and storage, semiconductor equipment, AI hardware). The rule buys
  the strongest names, so in a hot market it can only buy extended ones.
- **Names in the early range (+100–145%) exist but rank 13–20**, so the rule doesn't buy them:
  MRVL, MRNA, WBD, VLO, HPE, KLAC, FTNT, GLW. They're a mixed group (a chip designer, a vaccine
  maker, a media company, a refiner). That's what "early" looks like before you know the ending:
  most such lists don't become Nvidia.
- **"Caught early" is a hindsight label, not a signal.** It describes 4 stocks after the fact.
  Nothing tested here says a +100% name will outperform a +500% one next month. Buying ranks
  13–20 instead of 1–10 is a new rule and would need its own pre-registered test (top 20 did
  *worse* than top 10 here).

## Data fix: reused tickers

Massive's daily files are keyed by ticker symbol. When a symbol is reused, the price history joins
two different securities:
- **BNY** was a ~$10 municipal bond fund until early 2026. Bank of New York Mellon moved to the
  symbol in May 2026, after 104 days with no trades.
- **SPCX** was a ~$22 SPAC ETF. SpaceX listed under it in June 2026.

The first run treated both as having risen ~1,500% and ~340%. BNY was held for 3 months and SPCX
for 1, crowding out real candidates. The fix (`winners.momentum`) treats momentum as unknown when
its window has more than 10 trading days without a price. This is causal: at the time, you can see
the ticker didn't trade. The alternative, deleting the history before a gap, would also delete
companies that died, which is survivorship bias. The "biggest winners" report uses only the current
security's history (`current_listing`). Any new signal built on long price windows needs the
same guard.

## What this means

1. **"Finding the next Nvidia" in practice means momentum:** buy the strongest large companies,
   drop them when they stop leading. You catch the middle of the run, not the start.
2. **The return is real but it's a high-risk version of the market,** not alpha. After the data
   fix it slightly trails levered SPY on Sharpe. Judge it by Sharpe and drawdown, not CAGR.
3. **Size it as a satellite.** A −40% drawdown and −27% months in a small slice of the account
   are survivable; in the whole account they're how people quit at the bottom.
4. **Before trusting it:** test on more history (2016–2021 with the $79 Massive plan; it should
   include the 2020 crash-and-rebound, momentum's classic danger zone), and forward-test it on
   the IBKR paper account. It fits the daily book's structure (a monthly sleeve of target weights).

## Caveats

- Under 4 years of test data, in one strong bull market.
- Candidates were the 300 most-traded stocks each month. A few large but thinly traded companies
  could be missing from the top-200 universe.
- 4 variants tested; all 4 top-10/top-20 portfolios beat SPY on CAGR, but only the top 10s beat the
  equal-weight universe on Sharpe.
- The simulator lets cash go slightly negative: a position inside the 2% band stays overweight
  while new names are bought at full weight. Top 10 borrowed 0.6% of equity on average (6% at
  most) with no margin interest charged, worth roughly +0.3%/yr of CAGR. Negligible here, but
  it applies to every backtest that uses `backtest.sim`.
- A company that changed its ticker (e.g. BNY Mellon from BK) loses its momentum history for 12
  months after the change. That's conservative: it can only exclude a name, never create a fake
  signal.

## Sources

- Jegadeesh & Titman (1993), Returns to Buying Winners and Selling Losers. https://doi.org/10.1111/j.1540-6261.1993.tb04702.x
- Daniel & Moskowitz (2016), Momentum Crashes. https://doi.org/10.1016/j.jfineco.2015.12.002
- Bessembinder (2018), Do Stocks Outperform Treasury Bills? https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2900447
