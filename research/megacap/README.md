# Owning the biggest companies: top 10 / 50 / 100 vs the S&P 500 and Nasdaq-100

Run 2026-09-26 with `uv run python -m horizon_trader.backtest.megacap`. Code:
`src/horizon_trader/backtest/megacap.py`.

## Answer first

- **Over the long run (2008–2026), owning the biggest companies was about the same as owning
  the S&P 500.** Top 50 (XLG), top 100 (OEF) and mega-cap (MGC) all returned ~11.7–11.8% a
  year vs SPY's 11.4%, with the same ~50% crash in 2008–09.
- **The Nasdaq-100 (QQQ) was the clear winner**, at 16.4% a year. That's a bet on technology, which
  won this period. It isn't a law.
- **In the last 5 years a real top 10 beat the S&P 500** (15.9% vs 11.0% a year, price only), but
  with **more risk**: a 37% drawdown vs 25%, and 1.3x the market's moves. That period was
  dominated by a handful of AI and tech giants.
- **Hindsight is the trap.** Buying *today's* top 10 in Oct 2021 returns **35% a year**. The
  honest version, the top 10 *as known at each date*, returns **16%**. Lists of "just buy the
  biggest companies" usually show the 35% version.

## Part A: real index funds, Jan 2008 – Sep 2026

Dividends and fund fees included. Funds can't have hindsight; they held what their index held.

| Fund | What it holds | CAGR | Sharpe | Max drawdown | $10k becomes |
|---|---|---|---|---|---|
| SPY | S&P 500 (500 largest-ish, by size) | 11.4% | 0.64 | −51.9% | $74,907 |
| OEF | S&P 100 (the 100 largest) | 11.7% | 0.67 | −50.9% | $80,003 |
| XLG | S&P 500 Top 50 | 11.8% | 0.67 | −49.3% | $81,166 |
| MGC | Vanguard Mega Cap | 11.8% | 0.67 | −50.8% | $80,741 |
| **QQQ** | **Nasdaq-100** (tech-heavy) | **16.4%** | **0.79** | −49.4% | **$172,083** |
| RSP | S&P 500, **equal-weighted** | 10.2% | 0.57 | −55.8% | $61,824 |

**Years when the largest companies lagged** (calendar-year returns):

| Year | SPY | XLG (top 50) | QQQ | RSP (equal weight) |
|---|---|---|---|---|
| 2009 | 26% | 20% | 55% | 45% |
| 2010 | 15% | 9% | 20% | 21% |
| 2016 | 12% | 11% | 7% | 15% |
| 2022 | −18% | −24% | −33% | −12% |
| 2023 | 26% | 38% | 55% | 14% |
| 2024 | 25% | 33% | 26% | 13% |

Leadership rotates: after 2008 smaller companies (equal weight) led, in 2022 the giants fell hardest,
and in 2023–24 they led again.

## Part B: the top N by market cap at each date, Oct 2021 – Sep 2026

At the end of each month, rank US companies by market cap **as of that date** (Massive's
point-in-time shares outstanding), keep one share class per company (GOOG/GOOGL), and hold the
top 10 / 50 / 100 for the next month. Everything here, benchmarks included, is **price only**
(no dividends), so the comparison is fair.

| Portfolio | CAGR | Sharpe | Max drawdown | Volatility | Beta to SPY | Worst year |
|---|---|---|---|---|---|---|
| Top 10, weighted by size | 15.9% | 0.73 | −37.3% | 24.6% | 1.31 | −33.9% |
| Top 10, equal weight | 18.3% | 0.82 | −35.4% | 24.0% | 1.27 | −32.3% |
| Top 50, weighted by size | 13.7% | 0.77 | −28.2% | 19.2% | 1.08 | −24.8% |
| Top 50, equal weight | 11.4% | 0.76 | −26.9% | 16.0% | 0.89 | −19.2% |
| Top 100, weighted by size | 12.7% | 0.75 | −27.5% | 18.4% | 1.05 | −22.7% |
| Top 100, equal weight | 9.9% | 0.67 | −26.3% | 16.1% | 0.90 | −17.1% |
| SPY (S&P 500) | 11.0% | 0.69 | −25.4% | 17.3% | 1.00 | −19.5% |
| QQQ (Nasdaq-100) | 14.2% | 0.69 | −35.6% | 23.1% | 1.27 | −33.1% |
| OEF (S&P 100 fund) | 12.9% | 0.77 | −27.2% | 18.0% | 1.03 | −22.2% |
| XLG (Top 50 fund) | 12.6% | 0.72 | −28.7% | 19.0% | 1.07 | −25.2% |
| RSP (equal-weight S&P 500) | 6.0% | 0.44 | −22.5% | 16.2% | 0.85 | −13.2% |
| **HINDSIGHT:** today's top 10, bought Oct 2021 | **35.1%** | 1.12 | −40.7% | 31.5% | 1.51 | −37.7% |

**Cross-check:** our constructed top 100 (12.7%) matches the real S&P 100 fund (12.9%), and our top
50 (13.7%) is close to the real Top 50 fund (12.6%, which pays fees and follows slightly different
rules). So the point-in-time construction behaves like the real thing.

**The top 10 on 2021-10-29:** Microsoft, Apple, Alphabet, Amazon, Tesla, Berkshire Hathaway,
Nvidia, JPMorgan, Visa, UnitedHealth. **Today's top 10:** Nvidia, Apple, Alphabet, Microsoft,
Amazon, SPCX, Broadcom, Meta, Tesla, Micron. Four of the 2021 ten are gone from the list, and the
hindsight portfolio only works because it knew Nvidia, Broadcom and Micron would be there.

## What the research says

- **Arnott & Wu (2012), *The Winner's Curse: Too Big to Succeed?***: across decades and
  countries, the largest company in each sector has tended to **lag its own sector afterwards**
  (Research Affiliates reports roughly 3%+ a year over the following decade). Most #1 companies
  eventually lose the top spot.
- **Bessembinder (2018)**: all of the stock market's gains above cash came from about 4% of
  stocks. Owning the index guarantees you own them; picking a few names doesn't.
- The last few years (the AI boom) were unusually good for the giants. It's the exception
  Arnott's pattern allows, not proof the pattern is gone.

## So, is owning the biggest companies "good"?

**Yes, but it isn't a free lunch.**
- It's a reasonable, cheap way to own the market. Top 50/100 funds have matched or slightly
  beaten the S&P 500 since 2008.
- Concentrating in the top 10 adds return in eras like 2023–2025 and loses it in eras like
  2022, with bigger drawdowns throughout.
- Much of QQQ's outperformance is a technology bet that happened to win.

**At $5k**, a single fund (SPY, OEF, XLG or QQQ) does this for almost no cost. Building your own top
10 would mean 10 positions and monthly trades. At IBKR Tiered that's ~$0.35 minimum per order,
roughly $40–80 a year, or ~1–1.5% of a $5k account, which eats most of the difference.

## Sources

- Arnott & Wu (2012), The Winner's Curse: Too Big to Succeed? https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2088515
- Bessembinder (2018), Do Stocks Outperform Treasury Bills? https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2900447
- SPIVA U.S. Persistence Scorecard (S&P Dow Jones Indices). https://www.spglobal.com/spdji/en/spiva/article/us-persistence-scorecard/
