# How mid-frequency quant funds make money, and a reading list

Written 2026-09-28. Most quant capital isn't HFT: statistical-arbitrage and multi-manager funds
hold positions for days to months, the same horizons this repo works at. What separates them
from a solo trader is breadth, data, costs and risk control, not speed.

## The one formula: the fundamental law of active management

Grinold & Kahn: **IR ≈ IC × √breadth**

- **IC** is the correlation between your forecast and what happens next, across stocks.
  Good real signals have ICs of about **0.02–0.05**. That's tiny: most of every forecast is
  wrong.
- **Breadth** is the number of *independent* bets a year.
- **IR** (information ratio) is roughly the Sharpe ratio of the active part.

| setup | IC | bets a year | IR ≈ |
|---|---|---|---|
| 20 stocks, rebalanced monthly | 0.03 | 240 | 0.46 |
| 500 stocks, monthly | 0.03 | 6,000 | 2.3 |
| 3,000 stocks, weekly, 10 signals combined | 0.03 | 150,000+ | high, before costs and capacity |

This is why the funds trade thousands of names and combine dozens of weak signals, and why a
$5k account can't. At a $0.35 minimum per order, breadth costs more than a small IC earns
(see the weekly-reversal and ORB results in CLAUDE.md). The bets are never fully independent,
so the table is an upper bound.

## What they have that a solo trader doesn't

1. **Breadth and capital:** thousands of names, long and short, sized to hedge out market and
   sector risk, so what's left is mostly the signal.
2. **Costs:** commissions near zero, exchange rebates, smart execution, and borrowing at about
   the risk-free rate (retail: Fed funds + 1.5%). They can short almost anything, and they get
   leverage on market-neutral books (retail Reg T: 2x).
3. **Data:** point-in-time fundamentals, analyst estimates, and "alternative data" (card
   spending, satellite images, web traffic, text), all cleaned and free of survivorship bias.
4. **Risk models:** factor models (Barra-style) that measure and neutralise exposure to the
   market, sectors, size, momentum and so on. Many returns that look like skill are just
   factor exposure.
5. **Process:** research platforms that make lookahead hard, multiple-testing corrections, and
   capital given to strategies only after live paper trading. Pods cut losing teams fast.
6. **People and time:** teams of PhDs working full time, and years of institutional knowledge
   about what has already failed.

## What a solo quant can realistically do

- **Horizons of days to months,** where speed doesn't matter. That's already this repo's core.
- **Capacity-limited niches** too small for a $10B fund: small and illiquid stocks,
  special situations (index changes, spin-offs), text signals from filings read by an LLM
  (forward-test only, per CLAUDE.md).
- **Process over prediction:** pre-registration, point-in-time data, costs, holdouts,
  forward tests. This repo already does this better than most retail tools.
- **Honest expectations:** a good solo long-only tilt might add a little over the index at a
  similar risk. Anything claiming much more is usually overfit.
- **Cheap next steps for this repo:**
  - **Point-in-time fundamentals, free:** SEC XBRL [companyfacts
    API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces). Every
    fact has its `filed` date, so value and quality signals can be built without lookahead
    and joined to the Massive prices (all US stocks, delisted included).
  - **A ready-made signal library:** [Open Source Asset
    Pricing](https://www.openassetpricing.com) (Chen & Zimmermann) has 200+ published
    anomalies with code and data, to feed `alphas/` and test for decay after publication.
  - **Combine signals** into one score, neutralise by sector and beta, then judge against the
    equal-weight universe (the CLAUDE.md rule).

## Reading list

**Start here (books)**
- Grinold & Kahn, *Active Portfolio Management*: the fundamental law, information ratios,
  portfolio construction. The standard text.
- Marcos López de Prado, *Advances in Financial Machine Learning* (2018): backtest overfitting,
  labeling, cross-validation for time series.
- Robert Carver, *Systematic Trading* and *Leveraged Trading*: practical systematic trading for
  individuals, including position sizing and costs.
- Rishi Narang, *Inside the Black Box*: what quant funds actually do, without the math.
- Gregory Zuckerman, *The Man Who Solved the Market*: the history of Renaissance.
- Antti Ilmanen, *Expected Returns*: where returns come from, across asset classes.

**The classic signals**
- Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers*, Journal of
  Finance: cross-sectional momentum.
- Asness, Moskowitz & Pedersen (2013), [Value and Momentum
  Everywhere](https://onlinelibrary.wiley.com/doi/10.1111/jofi.12021), Journal of Finance
  ([free PDF](https://pages.stern.nyu.edu/~lpederse/papers/ValMomEverywhere.pdf)).
- Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum*, Journal of Financial Economics:
  the basis of this repo's trend sleeve.
- Frazzini & Pedersen (2014), *Betting Against Beta*, Journal of Financial Economics.
- Kakushadze (2016), [101 Formulaic Alphas](https://arxiv.org/abs/1601.00991): WorldQuant-style
  short-horizon formulas, the format `alphas/dsl.py` was built for.
- Gu, Kelly & Xiu (2020), [Empirical Asset Pricing via Machine
  Learning](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3159577), Review of Financial
  Studies: ML across ~900 signals. The strongest predictors are variants of momentum,
  liquidity and volatility. There's a free replication at [Tidy
  Finance](https://www.tidy-finance.org/blog/gu-kelly-xiu-replication/).

**Why most backtests lie (read these before believing any result)**
- Harvey, Liu & Zhu (2016), […and the Cross-Section of Expected
  Returns](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2249314): after hundreds of
  published factors, a new one needs **t > 3**, not 2.
- Hou, Xue & Zhang (2020), [Replicating
  Anomalies](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3275496): **65% of 452
  anomalies fail** a t > 1.96 test once microcaps are handled properly, and 82% fail the
  stricter multiple-testing bar.
- McLean & Pontiff (2016), [Does Academic Research Destroy Stock Return
  Predictability?](https://onlinelibrary.wiley.com/doi/10.1111/jofi.12365): published anomalies
  lose about half their return after publication (this repo saw it in ORB and noise-area).
- Bailey & López de Prado (2014), [The Deflated Sharpe
  Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551): correcting a Sharpe for
  how many things you tried (used in `orb_grid.py`).
- Bailey, Borwein, López de Prado & Zhu, [The Probability of Backtest
  Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253).

**Data to practise on (free)**
- [Kenneth French data library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html):
  factor returns since 1926.
- [AQR datasets](https://www.aqr.com/Insights/Datasets) and [Lasse Pedersen's
  data](https://www.lhpedersen.com/data): value, momentum, BAB, time-series momentum.
- [Open Source Asset Pricing](https://www.openassetpricing.com): signal-level data and code.
- [Tidy Finance](https://www.tidy-finance.org): a free book with Python and R code for
  empirical asset pricing.

## Building the five quant styles here (added 2026-09-29)

How each style funds run maps onto this repo at $5k, long-only, IBKR Tiered. Results
(2026-09-29): [multifactor.md](multifactor.md) (composites, Lazy Prices, learned weights) and
[risk_parity.md](risk_parity.md).

### How to combine signals (multi-factor), step by step
1. **Universe per month:** the point-in-time 200-500 largest US stocks from Massive (delisted
   included), as in `backtest/winners.py`.
2. **Raw signals,** each using only data known on that date. Fundamentals are keyed to the SEC
   `filed` date, never the fiscal period end.
3. **Make them comparable:** on each date, rank or z-score every signal across stocks
   (z = how many standard deviations above today's average), clip outliers at ±3, and flip
   signs so higher = better. Record each direction before testing (the `alphas/library.py`
   rule).
4. **Combine with equal weights first.** Two signals with Sharpe 0.4 each give about 0.57
   combined if uncorrelated, and 0.8 if they're -0.5 correlated (value and momentum are
   roughly that; Asness, Moskowitz & Pedersen 2013). Only move to IC-weighted blends over a
   trailing window once equal weight works; estimated weights usually overfit.
5. **Portfolio:** long the top 10-20 by composite score, equal weight or inverse-vol, per-name
   and sector caps, monthly rebalance through `compute_orders` (the 2% band limits turnover).
6. **Judge** against the equal-weight universe and SPY, with and without costs, and report
   each signal's IC plus the correlations between signals.

### The five styles
| Style | Buildable here? | Signals and data | Papers |
|---|---|---|---|
| Multi-factor equity | Yes, long-only tilt | momentum (have), value (earnings/cash-flow yield), quality (gross profits/assets), low vol, asset growth; fundamentals from SEC companyfacts | [Novy-Marx 2013](https://www.nber.org/system/files/working_papers/w15940/w15940.pdf), [Quality Minus Junk](https://papers.ssrn.com/abstract=2312432), [Value and Momentum Everywhere](https://pages.stern.nyu.edu/~lpederse/papers/ValMomEverywhere.pdf) |
| Trend / CTA | Already have (`position_trend`, ETFs). Futures are too big for $5k even as micros | 12-month TSMOM across asset-class ETFs | [A Century of Evidence on Trend-Following](https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing) |
| Multi-asset style premia | Partly: momentum across ETFs (have); value across countries possible; carry hard with ETFs | country ETFs, bond/commodity ETFs | [Value and Momentum Everywhere](https://pages.stern.nyu.edu/~lpederse/papers/ValMomEverywhere.pdf) |
| Risk parity | Yes, a cheap new sleeve | inverse-vol SPY/TLT/IEF/GLD/DBC with a vol target; 2022 (stocks and bonds down together) is the stress test | [Leverage Aversion and Risk Parity](https://www.aqr.com/Insights/Research/Journal-Article/Leverage-Aversion-and-Risk-Parity) |
| Events | Some | earnings announcement premium (already a candidate); index additions are dead ([Greenwood & Sammon 2025](https://papers.ssrn.com/abstract=4294297): 7.4% in the 1990s, 0.3% in the last decade); PEAD dead in large caps | [Frazzini & Lamont 2007](https://www.nber.org/papers/w13090) |

### Where text / NLP fits
Text is just one more column in the composite score. Two kinds:
- **Backtestable (no model memory):** word-list tone of 10-K/10-Q filings with the
  [Loughran-McDonald dictionary](https://sraf.nd.edu/loughranmcdonald-master-dictionary/), and
  **Lazy Prices** ([Cohen, Malloy & Nguyen, NBER w25084](https://www.nber.org/papers/w25084)):
  firms whose 10-K text changes a lot from last year underperform. Both need only EDGAR text
  and a similarity or word count, so they can be tested honestly on history.
- **Forward-test only:** anything an LLM reads (earnings releases, calls), because the model may
  know what happened next (see `llm_strategies_survey.md`). Log it with timestamps from now on.

### Honest expectations
A long-only multi-factor tilt in large caps has historically added a few percent a year before
costs, with multi-year stretches of losing to the index (value in 2018-2020). Massive only
covers 5 years (Sharpe standard error ~0.45), so check each signal's long-run record in [Open
Source Asset Pricing](https://www.openassetpricing.com) first and use our data as the recent,
point-in-time check.
