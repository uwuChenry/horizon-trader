# Papers With Backtest: why so many Sharpes above 1.5 (and one of 922), and three replications (2026-09-27)

The [awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading) list and its site [paperswithbacktest.com](https://paperswithbacktest.com/strategies) show hundreds of published papers "coded and run", many with Sharpe ratios of 1.5-2 and one of 922. This note audits those numbers and replicates the top-ranked strategies that fit this account (US stocks and ETFs).

**Bottom line**
- **The 922 is a division by almost zero.** After its December 2025 publication date, "[The Mechanical Virtue of Random Fourier Features](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5930257)" held no positions. Its NAV just earned T-bill interest (+0.3% a month with almost no noise), and the site's Sharpe doesn't subtract the risk-free rate: 3.9%/yr ÷ ~0% vol = 922. Over its full history the same strategy has a Sharpe of 0.09 and a 46% drawdown. Ironically, the paper itself shows how such performance arises mechanically, without any learning.
- **The high Sharpes are the top of a big pile.** The site's own [dataset page](https://paperswithbacktest.com/strategies/dataset) reports a median Sharpe of 0.32 over 4,312 papers: only 13 reach 1.5 and 97.6% stay below 1. The README shows the best 61 of 1,687 rows, and the list page ranks by Sharpe "which shows the catalog at its best by construction" (their words).
- **Most of the top rows have a mechanical explanation.** Three things recur in 93 audited pages:
  - T-bill interest counted as return: median Sharpe falls from 1.06 to 0.70 once T-bills are subtracted.
  - Today's S&P 500 back-tested from 1990 (23 of 93), which is survivorship bias.
  - Strategies that aren't the paper: the site's pipeline invents one when the paper has no trading rule, often just holding the index.
- **The three replications:**
  - **Dual-class arbitrage** (#1 on the site, Sharpe 1.97): stale prices. On liquid pairs it makes +0.3%/yr before costs.
  - **Short VIX** (1.64): the site shorts the VIX index, which can't be traded. Sized like the site, the tradeable version scores 1.6-3.1 at rf = 0 but only 0.45-0.7 after T-bills.
  - **Most Diversified Portfolio** (1.49): reproduced (24.7%/yr, Sharpe 1.17). Plain equal weight on the same survivors gets 19.3% and 1.18, while the real point-in-time equal-weight fund (RSP) made 10.7% and 0.71.
- Nothing here is worth trading. The catalogue is useful as a list of ideas; its headline numbers are not evidence.

## How the site produces its numbers

- **An automated pipeline.** 4,843 papers claimed in the README (4,312 measured on the dataset page), 1.8M lines of Python, a median of 457 per strategy. The code and replication notes are paywalled. Each strategy page shows its NAV (1990 onward, the same $100k or $10M start) and current positions, which is what this audit uses.
- **Common data, with proxies.** Nearly every NAV starts in 1990 on the site's own datasets. A paper about Europe, Germany or frontier markets runs on US S&P 500 names. Crypto papers have NAVs starting in 1990 or 1992, before Bitcoin existed.
- **Metrics.** Sharpe = mean / std of the whole NAV with **no risk-free rate**, gross of all costs. Idle cash in the NAV earns interest.
- **The site's own caveats are good.** The README gives t-stats and the (1.96 / Sharpe)² years rule. The dataset page shows the distribution, cites [Hou, Xue & Zhang (2020)](https://doi.org/10.1093/rfs/hhy131) and [Harvey, Liu & Zhu (2016)](https://doi.org/10.1093/rfs/hhv059), and reports in-sample vs out-of-sample by decile. The headline tables are what mislead.

## Audit (`uv run python -m horizon_trader.pwb.audit`)

This reads the NAV and positions from every strategy in the README table (61) and on the site's top-ranked list page (93 in total). Sharpe is recomputed from month-end NAV, once the site's way and once minus the 3-month T-bill ([FRED TB3MS](https://fred.stlouisfed.org/series/TB3MS)). Beta is against the S&P 500 total return index. Results are written to `data/pwb/audit.csv`.

| | README table (61) | all audited (93) |
|---|---|---|
| median headline Sharpe | 1.06 | 1.17 |
| median Sharpe from the page's NAV, rf = 0 | 0.73 | 1.06 |
| median Sharpe net of T-bills | **0.48** | **0.70** |
| share above 1.0, rf = 0 / net of T-bills | 38% / 20% | 52% / 25% |
| README Sharpe off from the page's own NAV by > 0.5 | 10 | 10 |
| today's S&P 500 back-tested from 1990 | 16 | 23 |
| holds only SPX/SPY (correlation > 0.9) | 5 | 5 |
| mostly T-bill interest (net Sharpe < 60% of the headline) | 6 | 13 |

**How each mechanism shows up, with examples:**
- **T-bills counted as return.** The site's NAV earns interest on cash, but its Sharpe doesn't subtract it. With T-bills averaging ~2.7% since 1990, a strategy at 3% vol gets about +0.9 of Sharpe for doing nothing. "Optimal Annuity Risk Management" (README 1.62) makes 0.6%/yr at 1.4% vol, so its Sharpe net of T-bills is -1.50. "Inconsistent investment and consumption problems" goes from 1.57 (its NAV, rf = 0) to 0.34.
- **README vs page.** Some README numbers don't match the NAV on the same strategy's page:
  - "The Investment CAPM": README 1.80, page NAV 0.01%/yr (Sharpe 0.01).
  - "Multi-Timeframe Trend on Bitcoin": 3.39 vs 0.48.
  - "Systematic Abnormal Return Variation": 1.57 vs 0.23.
- **Survivorship.** About a quarter hold ~495 of today's S&P 500 members, ABNB (listed 2020) included, in a NAV that starts in 1990. These include "Most Diversified Portfolio", "Kelly's Criterion", "1/N", risk parity and several "European"/"German"/"frontier market" papers. The survivorship replication below shows this alone is worth ~6%/yr.
- **The paper isn't a strategy.** Titles include annuity demand in Japan, errors in German Thomson data, and immigration quality. The pipeline still produces a NAV:
  - "Price Effects of Sovereign Debt Auctions in the Euro-zone" holds SPX (correlation 0.98).
  - "Rational Decision-Making … Biased Coin" is 0.2x SPY (correlation 1.00; net of T-bills -0.14).
  - The top two papers replicated below have no trading rule either.
- **Probable lookahead.** "The Anomalous Behavior of the S&P Covered Call Closed End Fund" holds only SPX, rebalances monthly, and shows 28.7%/yr at beta 0.55. Its NAV rose in 2008 (+6%) and 2022 (+36%). In the five days to 2022-04-19 it made +5.7% while SPX made +1.6%. A monthly SPX-only rule can't do that without knowing the future.
- **The 922.** It comes from the "Still working?" tab, which ranks by *out-of-sample* Sharpe. For a paper published in December 2025 that window is 9 months long, and the strategy was flat for all of it.

## Replication 1: dual-class share arbitrage (`uv run python -m horizon_trader.pwb.dual_class`)

The site's #1 is "[Self-Imposed Limits to Arbitrage](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1088553)" (Maymin 2011), at Sharpe 1.97, 7.7%/yr and 3.2% vol.
- **What the paper does.** It *explains* why HSBC, Royal Dutch/Shell and 3Com/Palm stayed mispriced (arbitrageurs cap their own position sizes). It has no trading rule.
- **What the site's code trades.** 7 US dual-class pairs (BF, CRD, GTN, HVT, MOG, TAP, WSO). Four of the B legs have zero volume on 41-58% of days.
- **Our rule, fixed before running:** textbook pairs trading ([Gatev, Goetzmann & Rouwenhorst 2006](https://doi.org/10.1093/rfs/hhj020)). A 60-day z-score of the log price ratio; open at |z| >= 2, close when z crosses 0; 1/N of equity per leg.
- **Costs.** Spreads come from daily high/low/close ([Abdi & Ranaldo 2017](https://doi.org/10.1093/rfs/hhx084)), plus IBKR Tiered commissions. Short borrow fees are not modelled.

| Pairs | Fill | Gross CAGR | Sharpe | Net of spread + IBKR ($5k) | Break-even half-spread |
|---|---|---|---|---|---|
| site's 7 | same close as the signal | +34.8% | 3.42 | +20.5% | 1.32% |
| site's 7 | next close | +15.6% | 1.76 | +2.8% (Sharpe 0.36, -52% DD) | 0.65% |
| site's 7 | next close, only on days the leg traded | +7.7% | 0.93 | -11.7% | 0.35% |
| site's 7, only while both legs trade and >= $1M/day | next close | +0.3% | 0.31 | -0.3% | 0.12% |
| 25 liquid US dual-class pairs, same filter | next close | +0.3% | 0.50 | -1.6% | 0.07% |

- **The edge is stale prices.**
  - Filling at the close you computed the signal from books bid/ask bounce that can't be traded.
  - Waiting one day halves it.
  - Filling only when the stock actually trades halves it again. Per pair, HVT/HVT-A drops from +25%/yr to +5%, and WSO/WSO-B from +20% to +4%.
  - What's left needs half-spreads below 0.35% on B shares that trade a few hundred shares a day. The spread estimator reads ~0 on no-trade days, so the "net" rows are optimistic.
- **Liquid pairs have nothing.** GOOGL/GOOG, FOXA/FOX, NWSA/NWS, LEN/LEN-B and HEI/HEI-A make +0.3%/yr gross and lose money after costs.
- **It gets better after the paper, which is the tell.** Same-close gross is +24%/yr to 2007 and +52% from 2008. A real arbitrage shrinks once published; stale quotes on ever-thinner B shares don't.

## Replication 2: short volatility (`uv run python -m horizon_trader.pwb.short_vix`)

"[Expectations and the Option Implied-Variance](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3763497)" (Mehta 2021) scores 1.64 on the site.
- **What the paper does.** It's an option-pricing model: VIX sits above realised variance because investors extrapolate past returns.
- **What the site's code trades.** A "cash/short VIX rule" on the VIX **index**. That can't be traded: there's nothing to borrow, and VIX futures only partly follow it (daily correlation 0.90).
- **Our rule, fixed before running:** short volatility when VIX is above the S&P 500's 21-day realised vol, else cash. Tested on the index (synthetic), short VIXY (VIX futures) and long SVXY (the ETF you can buy).

| Window | Instrument | Size | CAGR | Sharpe rf = 0 | Sharpe net of T-bills | Max DD |
|---|---|---|---|---|---|---|
| 1990-2026 | synthetic | full | -100% | -0.34 | -0.81 | -100% (VIX +116% on 2018-02-05) |
| 2011-10 to today | short VIXY | full | +26.4% | 0.71 | 0.63 | -87% |
| 2011-10 to today | SVXY | full | +10.9% | 0.54 | 0.49 | -94% |
| 1990-2026 | synthetic | 3% + T-bills | +1.4% | 0.46 | -0.54 | -19% |
| 2011-10 to today | short VIXY | 3% + T-bills | +3.0% | 1.56 | 0.71 | -3% |
| 2018-03 to today | SVXY | 3% + T-bills | +3.1% | **3.14** | **0.45** | -2% |

- **Why "3% + T-bills".** The site's 2.9% vol means a small position with the rest in cash. We couldn't reproduce its exact number: the code is paywalled, and a small short on the VIX index *loses* money over 1990-2026.
- **The last row is the general trick.** A sliver of a risky position plus T-bills gives a spectacular rf = 0 Sharpe (3.14) that is ordinary net of T-bills (0.45). This account's cash earns nothing (IBKR pays no interest on the first $10k), so rf = 0 Sharpes are honest here. On the site's NAVs they aren't.
- **At full size, short vol is ordinary.** Sharpe is ~0.5-0.7 with 87-94% drawdowns.
- **The timing rule adds nothing.** VRP > 0 is short 85% of the time and gives the same Sharpe as always short.

## Replication 3: survivorship in the portfolio-optimisation cluster (`uv run python -m horizon_trader.pwb.survivorship`)

The target is the Most Diversified Portfolio ([Choueifaty & Coignard 2008](https://doi.org/10.3905/JPM.2008.35.1.40)). On the site, "Properties of the Most Diversified Portfolio" scores 1.49 (23.1%/yr, 16.3% vol).
- **Setup.** Today's 503 S&P 500 members (228 had prices in 1989), monthly rebalancing, no costs.
- **Benchmark.** RSP is the point-in-time equal-weight S&P 500 fund (from 2003-05).

| 1990-01 to 2026-09 | CAGR | vol | Sharpe | net of T-bills | max DD |
|---|---|---|---|---|---|
| MDP on today's members | +24.7% | 20.5% | 1.17 | 1.04 | -38% |
| equal weight on today's members | +19.3% | 16.1% | 1.18 | 1.01 | -47% |
| S&P 500 total return | +11.0% | 14.7% | 0.78 | 0.60 | -51% |
| RSP (from 2003-06; same window below) | +10.7% | 16.4% | 0.71 | 0.60 | -56% |

- **We reproduce the site's MDP.** 24.7% vs its 23.1%.
- **Almost all of it is the universe.** Equal weight on survivors beats RSP in **every year 2003-2026**, by +5.6%/yr on average (smallest year: +1% in 2022).
- **The optimiser adds little.** Over 2003-2026 it lifts Sharpe from 1.07 to 1.26 on top of that. It's untested point-in-time: we have no historical S&P 500 membership.
- The same bias sits under "Kelly's Criterion" (1.31), "Meta-t" (1.34), "1/N" (1.32), "Generalized Risk-Based Investing" (1.25) and the other long-only S&P 500 rows. This is the same effect as `backtest.winners`, where today's 200 largest nearly doubled a point-in-time momentum result.

## Takeaways for this project

- **Read the site's t-stats and out-of-sample columns, and ignore the ranking.** Its own decile table shows the top in-sample decile keeping 0.87 of 0.95 after publication. On their common data that's regression to the mean. The real record is the median of 0.32.
- **Three checks catch most of these problems** before trusting any backtest (ours included):
  1. Subtract the risk-free rate when cash earns interest.
  2. Use a point-in-time universe.
  3. Fill only at prices that actually traded after the signal.
- **Ideas still worth a cheap test here, as listed in the survey, not because of their PWB Sharpe:** the earnings announcement premium and return seasonalities (`research/strategy_survey.md`). Carry and short-vol premia are real but come with crash risk, and FX is outside this account's scope.

## Sources

- The list: [awesome-systematic-trading README](https://github.com/paperswithbacktest/awesome-systematic-trading), [paperswithbacktest.com strategies](https://paperswithbacktest.com/strategies), [still working (OOS ranking)](https://paperswithbacktest.com/strategies/still-working), [dataset card](https://paperswithbacktest.com/strategies/dataset)
- [Cartea & Shi (2025), The Mechanical Virtue of Random Fourier Features and Model Complexity](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5930257), the 922 row
- [Maymin (2011), Self-Imposed Limits to Arbitrage](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1088553)
- [Mehta (2021), Expectations and the Option Implied-Variance](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3763497)
- [Choueifaty & Coignard (2008), Toward Maximum Diversification](https://doi.org/10.3905/JPM.2008.35.1.40)
- [Gatev, Goetzmann & Rouwenhorst (2006), Pairs Trading](https://doi.org/10.1093/rfs/hhj020)
- [Abdi & Ranaldo (2017), A Simple Estimation of Bid-Ask Spreads from Daily Close, High, and Low Prices](https://doi.org/10.1093/rfs/hhx084)
- [Hou, Xue & Zhang (2020), Replicating Anomalies](https://doi.org/10.1093/rfs/hhy131)
- [Harvey, Liu & Zhu (2016), … and the Cross-Section of Expected Returns](https://doi.org/10.1093/rfs/hhv059)
- [McLean & Pontiff (2016), Does Academic Research Destroy Stock Return Predictability?](https://doi.org/10.1111/jofi.12365)
