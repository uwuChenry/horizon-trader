# Multi-factor stock selection, Lazy Prices and learned weights (point-in-time top 200)

Run 2026-09-29, `uv run python -m horizon_trader.backtest.multifactor`. The rules were
pre-registered in the module docstring before any result was seen. Background:
[arbitrage_and_edges.md](../arbitrage_and_edges/README.md) and [quant_reading_list.md](../quant_reading_list/README.md).

**Verdict:** 2 of 3 pre-registered tests failed, and nothing beat the equal-weight universe.
- **Equal-weight composite:** it lowered risk (max drawdown -13% vs -17% for the universe)
  but also lowered Sharpe (0.60-0.81 net vs 1.06 for the equal-weight universe before costs).
- **Learned (ridge) weights:** they chased whichever style had just worked and did worse than
  fixed equal weights.
- **Lazy Prices:** the best single signal here (net Sharpe 1.02), but its IC isn't
  significant (t = 0.56). Adding it to the composite helped, yet the composite still trails
  the universe.

Four years of one bull market, so none of these differences are significant.

## Setup
- **Universe:** each month-end, the 200 largest US companies by market cap on that date
  (Massive, delisted included, one share class each). Formed at the close, traded at the next
  open, top 20 equal weight.
  - $5k IBKR Pro Tiered, 5 bps slippage, 2% band (the `winners.py` simulator).
  - Price only.
  - Formations Oct 2022 to Aug 2026; halves split 2024-10-12.
- **Fundamentals:** SEC XBRL company facts (`datasources/sec.py`). Only each company's **original
  10-K** is used, known from the day after it was filed. Amendments and restatements never
  leak backwards.
- **Signals:** each is turned into a cross-sectional rank z-score per date.
  - **momentum:** 12-1 month return.
  - **value:** the average of book-to-market and earnings yield.
  - **quality:** gross profits / assets
    ([Novy-Marx 2013](https://www.nber.org/system/files/working_papers/w15940/w15940.pdf)).
  - **low_vol:** minus the 1-year volatility of daily returns.
  - **lazy:** cosine similarity of the latest 10-K's words to the previous 10-K's
    ([Lazy Prices, Cohen, Malloy & Nguyen](https://www.nber.org/papers/w25084)).
- **Composites:** the plain average of the available z-scores, at least 3 required.
- **Ridge:** walk-forward ridge regression of next month's return rank on the five z-scores.
  It is trained only on months whose returns were known, uses an expanding window, starts
  after 12 months of training data, and its penalty equals the number of rows.

## Results

Rank IC is the correlation between a score and next month's returns across stocks.

| Score | Mean rank IC | t | Top 20 net CAGR | Net Sharpe | 1st half | 2nd half | Max DD | Beta |
|---|---|---|---|---|---|---|---|---|
| momentum alone | +0.009 | +0.26 | 29.6% | 0.94 | 0.62 | 1.16 | -36.0% | 1.46 |
| value alone | +0.013 | +0.45 | 15.0% | 0.90 | 0.63 | 1.18 | -17.1% | 0.75 |
| quality alone | -0.004 | -0.26 | 7.0% | 0.55 | 0.78 | 0.29 | -15.5% | 0.77 |
| low_vol alone | -0.046 | -1.09 | 2.1% | 0.24 | 0.67 | -0.14 | -13.1% | 0.29 |
| lazy alone | +0.005 | +0.56 | 15.5% | 1.02 | 1.05 | 0.97 | -19.2% | 0.85 |
| **composite 4 (no text)** | -0.032 | -1.00 | 7.1% | 0.60 | 0.76 | 0.45 | -13.2% | 0.52 |
| composite 5 (+ lazy) | +0.001 | +0.06 | 10.3% | 0.81 | 0.87 | 0.74 | -13.4% | 0.58 |
| ridge (learned weights) | -0.017 | -0.46 | 18.1% | 0.66 | 0.33 | 0.88 | -36.8% | 1.65 |
| 200 largest, equal weight (gross) | | | 15.3% | 1.06 | 1.26 | 0.88 | -17.3% | 0.89 |
| SPY (gross) | | | 19.2% | 1.22 | 1.55 | 0.93 | -19.0% | 1.00 |

Pre-registered verdicts:
1. Composite 4 beats the equal-weight universe (whole test and both halves): **FAIL**.
2. Lazy Prices adds value (composite 5 beats composite 4): **PASS**. That's weak evidence,
   because composite 4 is itself poor.
3. Learned weights beat equal weights (ridge beats composite 5): **FAIL**.

## What happened
- **The composite is a defensive tilt.** Low vol and value pull its beta down to 0.5-0.6. In
  a four-year rally that costs return, and low vol alone was the worst signal (IC -0.046).
  Momentum and value are -0.30 correlated, as the literature says, which is why combining
  them smooths the curve (max DD -13%). But smoothing is not beating: Sharpe fell.
- **Ridge chased the last regime.** Trained on the 2021-22 bear market, it put 88% of its
  weight on value. After the 2023 rally it swung to *minus* low vol, i.e. buying the most
  volatile stocks (-0.72 by late 2025), for a beta of 1.65 and a -37% drawdown. This is the
  answer to "why not let a model learn the weights": with IC around 0.01-0.05 and 3 years of
  data, the model fits noise and the market regime.
  [Gu, Kelly & Xiu](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3159577) made ML
  work with ~900 signals, 30,000 stocks and 60 years.
- **Lazy Prices** is the only signal whose portfolio kept a Sharpe near 1 in both halves, but
  its IC t-stat is 0.56, and 1.02 net vs the universe's 1.06 gross is no edge. Worth
  re-testing on a longer history, and with 10-Qs as in the paper (only 10-Ks here).
- **Momentum alone** (29.6% net, Sharpe 0.94, beta 1.46) repeats
  [winners_momentum.md](../winners_momentum/README.md): a levered bet on the rally.

## Caveats
- **4 years, one regime.** A Sharpe difference below ~0.5 isn't significant. Value's long
  drought (2018-2020) and low vol's good years (2022) are mostly outside this sample.
- **Quality covers ~122 of 200 names.** Banks and insurers have no gross profit, and SEC's
  company-facts feed drops segment-level figures. Oracle, Thermo Fisher and McDonald's
  report cost of revenue only that way, so they're missing.
  - After the first run, one missing cost tag (Uber-style filers) was added. Coverage went
    from 117 to 122 names and no verdict changed.
- **Missing quality tilts the composite toward banks** (found 2026-09-30, after the run). The
  composite averages the signals a stock *has*. Banks have no gross profit, so they're scored
  only on value, momentum and low vol, where they're strong. At the Aug 2026 formation, 10 of
  the top 20 were financials (TRV, CB, USB, BAC, ALL, BRK.B, JPM, C, MS, GS), plus 3 utilities.
  That's part of why beta is ~0.5. A fix (missing = 0, i.e. average, or sector-neutral ranks)
  would be a new pre-registered variant, not a re-run of this one.
- **Fundamentals come from the annual 10-K only, so they go stale.** Micron's Aug 2026 scores
  use its FY2025 10-K (filed Oct 2025), so they don't reflect the 2026 memory upswing (quality
  z = -1.02). Adding 10-Q data would make the scores current.
- **The equal-weight benchmark is judged before costs.** 200 names at $5k are $25 positions,
  at the simulator's $25 dust threshold, so its "net" run isn't a real portfolio. Judging it
  gross is stricter for the strategies. This was also changed after the first run, and the
  verdicts were the same either way.
- A few companies re-registered under a new CIK (ExxonMobil's 2026 holding company, SpaceX)
  have no 10-K facts yet, so their fundamentals are missing for the most recent months.
- Price only (no dividends), which slightly understates value and low-vol stocks.

## Next
- A longer history is the only thing that can make any of this significant. Options: Massive
  Developer for 2016-2021 prices, plus SEC facts, which go back to ~2009.
- If continued: Lazy Prices with 10-Qs, then re-test composite 5 on the new years, with its
  definition kept exactly as it is here.
