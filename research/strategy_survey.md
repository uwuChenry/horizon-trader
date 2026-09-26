# Strategy survey: swing and intraday papers (2026-09-25)

Which published strategies are still worth testing for a <$5k IBKR account (large caps and ETFs, a few trades a day at most), and what happened when the top two were replicated. Every paper is linked in place and listed under Sources at the end.

**Bottom line**
- Most famous calendar and intraday edges have faded since publication.
- The best candidate, SPY noise-area intraday momentum, replicates strongly *inside* the paper's sample. After publication it's about half as good, and it only beats buy-and-hold before costs at $100k scale. At $5k with IBKR Fixed it loses money after publication.
- Last-half-hour momentum is gone in 2021-2026 data.

## How much to trust a published edge

- [McLean & Pontiff (*JF* 2016)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156623) studied 97 published predictors. Returns were 26% lower out-of-sample and 58% lower after publication, and the decline is largest for the strongest in-sample results.
- [Jensen, Kelly & Pedersen (*JF* 2023)](https://www.nber.org/papers/w28432): most factors do replicate and survive out-of-sample (93 countries). "Real" is a lower bar than "tradeable at $2 per round trip", though.

## Candidates, ranked for this account (before testing)

1. **SPY noise-area intraday momentum** ([Zarattini, Aziz & Barbon 2024, "Beat the Market"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172)).
   - Claim: 19.6% CAGR and Sharpe 1.33 for 2007 to early 2024, net of $0.0035/share commission plus $0.001/share slippage. It uses up to 4x leverage. Rule details are in the [CXO summary](https://www.cxoadvisory.com/momentum-investing/complex-intraday-time-series-momentum-strategy-applied-to-spy/).
   - Mechanism: [Baltussen, Da, Lammers & Martens (*JFE* 2021)](https://academicweb.nd.edu/~zda/intramom.pdf) find the same late-day momentum in more than 60 futures markets from 1974 to 2020. They trace it to options dealers and leveraged ETFs hedging their gamma exposure, which forces them to trade with the day's move.
   - An [independent ES-futures replication](https://www.quantitativo.com/p/intraday-momentum-for-es-and-nq) from 2010 with realistic costs got 8.1% CAGR, Sharpe 0.91 and a 24% max drawdown, against 12.4% for buy-and-hold. It was flat from 2010 to 2017.
   - Ignore [Maróy (2025)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5095349), which claims a Sharpe above 3: its parameters were optimized on the same data.
2. **Last-half-hour momentum** ([Gao, Han, Li & Zhou, *JFE* 2018](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2440866); Baltussen et al. 2021). The return up to 30 minutes before the close predicts the last half hour. One trade a day.
3. **Earnings-call text drift** ([Meursault, Liang, Routledge & Scanlon, "PEAD.txt", *JFQA* 2023](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3778798)).
   - Classic earnings drift (PEAD) has been dead in large caps since about 2006 ([Martineau, *CFR* 2022](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3111607)).
   - The 2025 "PEAD is back" results only hold with microcaps: t falls from 2.18 to 1.43 without them ([UCLA Anderson brief](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/)).
   - A surprise measured from the call *text* still drifts in recent years.
   - It's a natural use of Claude, but **forward-test only** because the model may have seen the outcomes.
   - *Downgraded after the LLM survey* (`llm_strategies_survey.md`): for large caps, press-release content is priced by the next open ([Wu, Akin, Martineau et al. 2025](https://arxiv.org/abs/2509.24254)), and call-transcript tone peaks the next day ([Yu et al. 2026](https://arxiv.org/abs/2606.29734)). A multi-week drift trade on large caps has little support. The better LLM use is the monthly "time-capsule" score described there.
4. **Earnings announcement premium** ([Frazzini & Lamont 2007](https://papers.ssrn.com/abstract=986940)).
   - Weakened overall, but it persists among the largest announcers.
   - Monthly, daily data, cheap to test.
   - Use only earnings dates announced in advance.
5. **Return seasonalities** ([Keloharju, Linnainmaa & Nyberg, *JF* 2016](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2224246)). Same-calendar-month returns, 13% a year as a long-short portfolio. A quick rank-IC check.

## Faded or not tradeable here

| Strategy | Evidence |
|---|---|
| Pre-FOMC drift ([Lucca & Moench 2015](https://www.newyorkfed.org/research/staff_reports/sr512.html)) | Essentially gone after 2015 ([Kurov, Wolfe & Gilbert 2021](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3134546)) |
| Overnight drift, 2-3am ET ([Boyarchenko, Larsen & Whelan, *RFS* 2023](https://www.newyorkfed.org/research/staff_reports/sr917)) | About zero since 2021 ([NY Fed Liberty Street, July 2026](https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/)) |
| Turn-of-the-month, US ETFs ([McConnell & Xu 2008](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=917884)) | Classic window not significant after 2015; the trading version lags buy-and-hold on CAGR and Sharpe ([QuantSeeker re-test](https://www.quantseeker.com/p/turn-of-the-month-strategies-do-they)) |
| Classic PEAD, large caps | Dead since about 2006 ([Martineau 2022](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3111607)) |
| 52-week-high momentum ([George & Hwang 2004](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2004.00695.x)) | Limited to small stocks ([Barroso & Wang 2021](https://acfr.aut.ac.nz/__data/assets/pdf_file/0005/576995/Haoxu-Wang-paper_NZFM.pdf)) |
| QQQ 5-minute ORB ([Zarattini & Aziz 2023](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622)) | $0.0005/share commission, no slippage: the same weakness found in our [Stocks-in-Play ORB](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284) replication |
| RSI(2) mean reversion | Already tested here: Sharpe 0.41 |

Related: in [Lou, Polk & Skouras (*JFE* 2019)](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf), momentum in large stocks is earned mostly overnight. That's interesting, but trading it takes a daily round trip, which costs too much here.

## Replication: SPY market intraday momentum (2021-10 to 2026-09)

`uv run python -m horizon_trader.intraday.market_momentum` uses Massive minute bars and paper defaults with nothing tuned:
- 14-day noise band, HH:00/HH:30 checks, VWAP trailing stop.
- 2% daily vol target, at most 4x.
- Signal at the close of the minute, fill at the next bar's open, exit at the official close.

Post-publication means from 2024-05-15 onward. The paper's own sample includes 2021-10 to 2024-05, so the "pre-pub" rows are **in-sample for the paper**.

**Signal quality before costs, unlevered:**

| Strategy | Period | bps/trade | Hit rate | t (daily) | Sharpe 1x |
|---|---|---|---|---|---|
| Noise area | pre-pub | +5.4 | 43% | 2.90 | 1.82 |
| Noise area | post-pub | +1.3 | 40% | 0.74 | 0.48 |
| Last half hour, rest-of-day signal (Baltussen) | pre-pub | +1.4 | 52% | 1.23 | 0.77 |
| Last half hour, rest-of-day signal | post-pub | **-1.4** | 47% | -1.48 | -0.97 |
| Last half hour, first-half-hour signal (Gao) | all | +0.3 | 50% | 0.41 | 0.18 |
| Control: always long the last half hour | all | +0.1 | 50% | 0.13 | 0.06 |

Noise area by year (bps/trade): 2021 +2.2, 2022 +6.9, 2023 +5.7, 2024 +3.0, 2025 +1.7, 2026 -0.8.

**Portfolios** (2% vol target, at most 4x, average leverage about 2.5x):

| Setup | Period | CAGR | Sharpe | Max DD |
|---|---|---|---|---|
| Noise, $100k, paper costs | all | 17.5% | 1.21 | -19% |
| Noise, $100k, paper costs | post-pub | 6.8% | 0.52 | -19% |
| Noise, $5k, IBKR Fixed, 0.5c slip | all | 8.0% | 0.62 | -26% |
| Noise, $5k, IBKR Fixed, 0.5c slip | post-pub | **-2.9%** | -0.13 | -29% |
| Noise, $5k, IBKR Tiered, 0.5c slip | all / post-pub | 12.5% / 2.2% | 0.92 / 0.22 | -23% |
| Noise, $5k, Fixed, 1x (no vol target) | all | -2.2% | -0.31 | -19% |
| Last half hour (rest-of-day signal), $5k, Fixed | all | -14.0% | -1.74 | -57% |
| SPY buy & hold | all / post-pub | 11.2% / 17.0% | 0.70 / 1.06 | -25% / -19% |

**Robustness check on QQQ** (`--ticker QQQ`; its data was cached alongside SPY's as a planned check. The paper tests SPY only):

| Setup | Period | CAGR | Sharpe | Max DD |
|---|---|---|---|---|
| Signal before costs, unlevered | pre-pub / post-pub | +7.0 / +5.8 bps/trade | t 2.9 / 2.0 | |
| Noise, $100k, paper costs | all / post-pub | 23.2% / 20.1% | 1.59 / 1.26 | -15% |
| Noise, $5k, IBKR Fixed, 0.5c slip | all / post-pub | 14.3% / 10.9% | 1.06 / 0.75 | -17% / -18% |
| Noise, $5k, IBKR Tiered, 0.5c slip | all / post-pub | 18.7% / 15.3% | 1.33 / 1.02 | -16% |
| QQQ buy & hold | all / post-pub | 14.7% / 23.2% | 0.71 / 1.08 | -36% / -23% |

- On QQQ the effect survives publication: +5.8 bps/trade, positive every year 2021-2026.
- After publication it earns less than buy-and-hold (15% vs 23%) at a similar Sharpe, with a shallower drawdown. It's flat overnight, so it should diversify the daily sleeves.
- The last-half-hour signal fails on QQQ too.
- **Selection warning:** picking QQQ *because* SPY failed is exactly the cherry-picking this project avoids. Two tickers is a thin basis.
- An IWM/DIA cross-check was considered and **skipped (owner's call, 2026-09-25)**. The out-of-sample test for QQQ is therefore forward data: paper-trade it on the IBKR paper account, which also measures real fills.

**Verdict**
- **Noise area:** the effect is real in the paper's own sample (t = 2.9) and survives costs at $100k. After publication it is weaker (t = 0.7) and below SPY buy-and-hold on every setup.
  - At $5k, IBKR Fixed's $1 minimum takes about $2.30 of each trade's ~$2-4 gross.
  - Tiered pricing roughly halves that, but still leaves it below SPY after publication.
  - It is not worth trading on SPY at $5k now.
  - QQQ is the open question: it held up after publication (Sharpe 1.02 at $5k Tiered). Treat it as a paper-trading candidate, not a result.
- **Last half hour:** dead in this sample. The rest-of-day signal is negative after publication, and the first-half-hour signal is noise.

**Caveats**
- About 4.5 years of data, only about 2.3 of them post-publication.
- Slippage is a fixed per-share assumption, not measured. SPY's spread is 1c, so 0.5c is half the spread.
- Reversals are charged as two orders.
- Unadjusted prices, so ex-dividend days slightly distort the band.

## Sources

- Zarattini, Aziz & Barbon (2024), Beat the Market: An Effective Intraday Momentum Strategy for SPY. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172
- CXO Advisory summary of the noise-area rules. https://www.cxoadvisory.com/momentum-investing/complex-intraday-time-series-momentum-strategy-applied-to-spy/
- Quantitativo, Intraday Momentum for ES and NQ (independent replication). https://www.quantitativo.com/p/intraday-momentum-for-es-and-nq
- Maróy (2025), Improvements to Intraday Momentum Strategies. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5095349
- Baltussen, Da, Lammers & Martens (2021), Hedging Demand and Market Intraday Momentum, JFE. https://academicweb.nd.edu/~zda/intramom.pdf
- Gao, Han, Li & Zhou (2018), Market Intraday Momentum, JFE. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2440866
- McLean & Pontiff (2016), Does Academic Research Destroy Stock Return Predictability?, JF. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156623
- Jensen, Kelly & Pedersen (2023), Is There a Replication Crisis in Finance?, JF. https://www.nber.org/papers/w28432
- Meursault, Liang, Routledge & Scanlon (2023), PEAD.txt: Post-Earnings-Announcement Drift Using Text, JFQA. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3778798
- Martineau (2022), Rest in Peace Post-Earnings Announcement Drift, CFR. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3111607
- UCLA Anderson Review, Is Post-Earnings Announcement Drift a Thing Again? https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/
- Frazzini & Lamont (2007), The Earnings Announcement Premium and Trading Volume. https://papers.ssrn.com/abstract=986940
- Keloharju, Linnainmaa & Nyberg (2016), Return Seasonalities, JF. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2224246
- Lucca & Moench (2015), The Pre-FOMC Announcement Drift, JF. https://www.newyorkfed.org/research/staff_reports/sr512.html
- Kurov, Wolfe & Gilbert (2021), The Disappearing Pre-FOMC Announcement Drift. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3134546
- Boyarchenko, Larsen & Whelan (2023), The Overnight Drift, RFS. https://www.newyorkfed.org/research/staff_reports/sr917
- NY Fed Liberty Street Economics (2026), The Disappearing Overnight Drift. https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/
- McConnell & Xu (2008), Equity Returns at the Turn of the Month. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=917884
- QuantSeeker, Turn-of-the-Month Strategies: Do They Still Work? https://www.quantseeker.com/p/turn-of-the-month-strategies-do-they
- George & Hwang (2004), The 52-Week High and Momentum Investing, JF. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2004.00695.x
- Barroso & Wang, What Explains Price Momentum and 52-Week High Momentum When They Really Work? https://acfr.aut.ac.nz/__data/assets/pdf_file/0005/576995/Haoxu-Wang-paper_NZFM.pdf
- Zarattini & Aziz (2023), Can Day Trading Really Be Profitable? (QQQ ORB). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622
- Zarattini, Barbon & Aziz (2024), A Profitable Day Trading Strategy for the U.S. Equity Market (Stocks-in-Play ORB). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
- Lou, Polk & Skouras (2019), A Tug of War: Overnight Versus Intraday Expected Returns, JFE. https://personal.lse.ac.uk/polk/research/TugOfWar.pdf
- Wu, Akin, Martineau et al. (2025), Extracting the Structure of Press Releases. https://arxiv.org/abs/2509.24254
- Yu et al. (2026), Fast Numbers, Slow Language. https://arxiv.org/abs/2606.29734
