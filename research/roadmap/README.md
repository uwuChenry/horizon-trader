# Research roadmap (2026-10-01)

Where the research stands, what to test next, and which data would improve the signals.
Detailed results live in the notes linked below. `CLAUDE.md` has the full evidence table.

**Portfolio/data review update (2026-10-01):** see the
[new review](../portfolio_data_review/README.md) and the dated addendum at the
end of this file. They update the priorities and correct the earnings-calendar,
data-retention and combined-Sharpe assumptions below. Earlier notes are preserved
as the research record.

## Where we stand

**What works (as risk premia, not alpha):**

| Strategy | Evidence | Status |
|---|---|---|
| Vol-managed SPY | Most robust result: Sharpe 0.66-0.80 across the parameter grid, 1.00 out-of-sample from 2013 | Core |
| ETF 12-1 momentum | Sharpe 0.76, but only the 12-month lookback survives | Core |
| Risk parity | Sharpe 0.74, only 0.59 correlated with momentum ([risk_parity.md](../risk_parity/README.md)) | Tested replacement for trend, not switched on |
| ORB top-1, stop-limit | Sharpe ~0.72 at $5k, about 0 correlation to the book ([orb_experiments.md](../orb_experiments/README.md)) | Paper-trade candidate |
| QQQ noise-area momentum | Held up after publication, t = 2.0 ([strategy_survey.md](../strategy_survey/README.md)) | Paper-trade candidate, but chosen after SPY failed |
| Combined book | Sharpe 0.83, -12% max drawdown | Lower return than SPY (6.5% vs 11.3%), much smaller drawdowns |

**What's dead:** classic indicators (MACD, EMA, RSI(2); [ema_vwap.md](../ema_vwap/README.md)), last-half-hour
momentum, gold vs dollar ([gold_dollar.md](../gold_dollar/README.md)), ETF ORB ([etf_orb.md](../etf_orb/README.md)),
copying Congress ([congress.md](../congress/README.md)), the multi-factor composite
([multifactor.md](../multifactor/README.md)), LLM-mined formulas, and every parameter-tuned ORB variant
([orb_parameter_grid.md](../orb_parameter_grid/README.md)).

**The honest diagnosis:** no real stock-picking alpha yet. Nothing has cleared t > 2 in its
claimed direction. What we have is cheap, diversified exposure to known premia, plus one or two
intraday overlays. Three things limit us, and none of them is a shortage of ideas:

1. **The cost floor.** At $5k, a $0.35-$1 minimum per order kills anything that trades often.
2. **Short samples.** Most intraday and point-in-time tests cover about 4-5 years of one bull
   regime. Over 2.5-year halves, the standard error of Sharpe is about 0.6.
3. **Multiple testing.** 480 ORB configs, 14+ pre-registered ideas, 20 alphas and many
   variants. The more we try, the more likely the best row is luck. Published edges also shrink:
   [McLean & Pontiff (*JF* 2016)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156623)
   find returns 58% lower after publication.

So the highest-value next step is **out-of-sample data**, not idea number 50.

## What to explore, ranked for this account

1. **Validate what we already have on 2016-2021.** This is the cheapest way to make a result
   believable. It's a fresh test set for the ORB candidate (relvol >= 12, no entries after
   10:30), for QQQ noise momentum and for point-in-time winners momentum. The pass/fail rules
   already exist, so nothing has to be re-tuned.
2. **Insider buying (SEC Form 4).** Copying Congress failed mostly on the 32-day filing lag.
   Insiders file within 2 business days and know more.
   [Cohen, Malloy & Pomorski (*JF* 2012), "Decoding Inside Information"](https://corpgov.law.harvard.edu/2012/02/03/decoding-inside-information)
   split insiders into "routine" traders (who trade in the same month every year, and predict
   nothing) and "opportunistic" ones, whose trades earn 82 bps a month value-weighted.
   Cluster buys by several insiders are the classic signal. The data is free on EDGAR,
   `datasources/sec.py` already has the plumbing, and the event study can reuse
   `congress/event_study` almost unchanged. Expect a weaker effect in large caps.
3. **Earnings announcement premium**
   ([Frazzini & Lamont 2007](https://papers.ssrn.com/abstract=986940)). Ranked #4 in
   [strategy_survey.md](../strategy_survey/README.md) and never tested. Point-in-time announcement dates
   can come from the acceptance timestamps on 8-K Item 2.02 filings, which we can already
   download. Use only dates known in advance. About 12 trades a year, so costs barely matter.
4. **Risk-managed momentum**
   ([Barroso & Santa-Clara, *JFE* 2015, "Momentum Has Its Moments"](https://doi.org/10.1016/j.jfineco.2014.11.010)).
   Scale the momentum sleeve by its own recent volatility, the same idea that made the SPY
   sleeve our most robust result. The paper finds it nearly doubles momentum's Sharpe and
   removes most crashes. Daily data and existing code; it mainly targets crashes like July
   2026's -27% in the winners portfolio.
5. **Return seasonalities**
   ([Keloharju, Linnainmaa & Nyberg, *JF* 2016](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2224246)).
   A quick rank-IC check through `alphas.cli evaluate`, about an hour of work. Expect it to be
   weak in large caps.
6. **Crypto trend.** Time-series momentum on BTC/ETH
   ([Liu & Tsyvinski, "Risks and Returns of Cryptocurrency"](https://www.nber.org/papers/w24877)
   find strong time-series momentum and no exposure to stock-market factors). Crypto is in
   scope, data is free, and it's the most uncorrelated asset we could add. Model the fees
   honestly (IBKR's crypto goes through Paxos).
7. **Options-implied signals.** The implied-volatility smirk
   ([Xing, Zhang & Zhao, *JFQA* 2010](https://ideas.repec.org/a/cup/jfinqa/v45y2010i03p641-662_00.html):
   steepest-smirk stocks trail the flattest by 10.9% a year, risk-adjusted) and the call-put
   implied-volatility spread
   ([Cremers & Weinbaum, *JFQA* 2010](https://ideas.repec.org/a/cup/jfinqa/v45y2010i02p335-367_00.html):
   50 bps a week, but shrinking over their own sample). The one signal class we haven't
   touched. Needs options data (below).

**Skip:** daily news sentiment, LLM trading agents, time-series foundation models, S&P inclusion
effects, pre-FOMC drift and turn-of-month. Already documented as dead in
[strategy_survey.md](../strategy_survey/README.md) and [llm_strategies_survey.md](../llm_strategies_survey/README.md).

**Portfolio-level point:** the owner's ~$100k long-term account is ~63% semis. A $5k strategy
that's uncorrelated to semis is worth more than one with a slightly higher Sharpe. That favours
ORB, crypto trend and risk parity over more large-cap momentum.

## What data would improve the signals

| Priority | Data | Cost | What it unlocks |
|---|---|---|---|
| 1 | **IBKR paper fills** | Free (+ data below) | Tests the plumbing; slippage including the bid/ask spread for stop-market orders (see caveat below) |
| 2 | **Massive minute bars, 2016-2021** (one month of a higher plan) | One month's fee | Out-of-sample test for everything intraday and point-in-time |
| 3 | **EDGAR Form 4 + 8-K 2.02 timestamps** | Free | Insider-trading signal and point-in-time earnings dates |
| 4 | **FINRA short interest** (twice a month) | Free | Days-to-cover as a filter on long candidates |
| 5 | **Daily prices with delisted names back to the 1990s** (e.g. Norgate) | A few hundred $/yr | Tests momentum and multi-factor across more than one regime (today: 4 years) |
| 6 | **Options history** (Massive options or CBOE DataShop) | $$ | Smirk and IV-spread signals, plus the defined-risk options planned for later |

**What IBKR paper fills can and can't measure.** Paper orders fill against the live quote, so
a paper stop-market order shows the bid/ask spread and the trigger delay. That's the part our
1-second bars can't see, which is why their 4.5c is a floor. Paper fills ignore queue position,
though: a paper limit order fills as soon as the price touches it, as if first in line, so
**stop-limit fill rates on paper are optimistic**. Paper results also aren't evidence of an
edge. The final check for slippage is a few tiny live trades, which need the owner's explicit
go-ahead.

**Not worth it at this size:** credit-card, satellite or news feeds, and analyst revisions
(I/B/E/S). They're priced for funds, and the edge decays faster than we can trade it at $2 per
round trip.

## Setup status (2026-10-01)

- IBKR paper account connected through IB Gateway on port 4002 (`execution.ibkr` check passes).
  The balance is still the $1M default. Plan: size the daily book from a virtual
  `capital: 5000` with its own ledger (never `NetLiquidation`, which includes interest on $1M),
  and reset the paper balance to $5k before paper-trading the intraday overlays, because 4x
  intraday margin and pattern-day-trader behaviour only show up at the real size.
- All strategies share one account, with an IBKR `orderRef` tag per strategy and one ledger
  each; splitting $5k into separate accounts hurts the intraday sleeves
  ([portfolio_mix.md](../portfolio_mix/README.md)).
- Market data: subscriber status switched from Professional (IBKR's default) to
  Non-Professional. Subscribed to the US Securities Snapshot and Futures Value Bundle
  ($10/month, waived at $30 of monthly commissions) and the US Equity and Options Add-On
  Streaming Bundle ($4.50/month), which streaming through the API needs. Share it with the paper
  account in the paper-account settings. Only one session can stream at a time, so logging in
  to the live user elsewhere cuts off the paper feed.

## Next, in order

1. Build the IBKR paper adapter (`Broker` protocol, `DU`-only guard, per-order and daily caps,
   kill-switch file, reconciliation, a fill log with IBKR's actual commissions next to the
   modeled cost) and a daily shadow run of the book. Then paper ORB with both stop-market and
   stop-limit entries, comparing fills against the 1-second-bar estimates.
2. Run the insider and earnings-premium tests, which only need free data.
3. Buy one month of Massive history for 2016-2021 and run the pre-registered retests in one go.

## Portfolio and data addendum (2026-10-01)

The owner's budget is **under $100/month, with occasional one-time purchases**.
The [completed portfolio review](../portfolio_data_review/README.md)
replayed the existing strategies, audited the actual files and checked official
data-product documentation. Reproduction commands, a full experiment ledger,
source hashes and offline figures are saved with it.

**Change the selection criterion:** standalone Sharpe below one does not reject a
sleeve. Evaluate its net contribution to the existing portfolio. The daily core's
observed return correlation is +0.05 with baseline ORB and -0.05 with QQQ noise,
versus +0.74 with standalone risk parity. That makes the intraday combination worth
testing in a real account model. The previous daily-plus-noise 1.69 Sharpe is
reproducible arithmetic; it becomes 1.44 after a cash hurdle and 1.14 with current
Fixed-cost replays. It has not yet been demonstrated under shared-account margin,
minimum fees, whole shares and order netting.

Frozen inverse-volatility screening weights (51.60% core / 20.33% ORB / 28.07%
noise, estimated on 2021-23) produce excess Sharpe 0.83 overall and 1.12 in reused
2024+ history. A fixed reduced overlay reaches 1.09 overall, falling to 0.96 with
additional slippage. These are return-stream screens; none certifies executable
Sharpe above one or completion of the QQQ return/drawdown objective.

**Revised next sequence:**

1. Replay the frozen strategies in one funded account, with shared buying power,
   net orders, raw shares/dividends and actual minimum fees. Compare with QQQ total
   return and exposure/risk controls on identical dates. Add no strategy parameters.
2. Collect timestamped quotes/scanner/order/fill observations using the existing
   infrastructure. The adapter is built; this audit found no recorded broker fills.
   Paper evidence tests implementation and modeled costs, with simulated fills.
3. For existing intraday validation, prioritize **Massive Stocks Developer at
   $79/month**: ten years of history, approximately late 2016 onward at this date.
   Extend point-in-time reference/corporate-action data alongside bars. Check
   retention rights before assuming one month buys a permanent archive. Older
   history is new to the repository, not necessarily independent of paper selection.
4. For a distinct data branch, prefer **daily cross-asset futures** before options:
   Norgate Futures is $148.50/6 months or $270/year, paid upfront. It requires an
   ongoing subscription to retain raw exports. Developer plus the annual-equivalent
   futures cost is $101.50/month before broker feeds, so treat these as alternatives.
   A targeted Databento historical quote is another one-off route; actual cost is
   unknown until the basket is quoted.
5. Use free SEC Form 4 documents for one bounded insider test after transaction
   parsing and historical-universe validation. Defer paid options until a specific
   SPY/QQQ historical EOD-chain pilot passes sample-quality and budget checks.

**Corrections to earlier entries:**

- 8-K acceptance timestamps identify filings, **not earnings dates announced in
  advance**. They can support a post-filing study with an availability delay; the
  pre-announcement premium needs separately archived calendar announcements.
- The Form 4 cache contains filing metadata, not transaction XML or a finished
  insider-buying signal. Parse transaction codes, amendments and availability first.
- FINRA short interest must be lagged to publication, not its settlement date.
- Current options Greeks snapshots are not historical chain snapshots. Cheap bars
  alone do not support credible historical IV-smirk/spread tests.
- Crypto's diversification must be measured, especially on equity stress days;
  it is not established as the most uncorrelated addition.
- The unlevered ETF cycle's failure does not imply that levering QQQ is the only
  alternative. It motivates testing portfolio complementarity with proper accounting.

Official price/coverage/licensing links and limitations are in the
[review](../portfolio_data_review/README.md) and
[vendor note](../portfolio_data_review/vendor_futures_options.md).
The [inventory](../portfolio_data_review/local_data_inventory.md) records
1,253 local minute/daily dates, 60 monthly point-in-time universe dates, selected
second-bar windows rather than quotes, and no dedicated futures/options dataset.
No subscriptions or live trading settings were changed by this review.

## Forward tests: what each one decides (2026-11-05)

A forward test earns its keep only if it feeds a dated decision. State on 2026-11-05:

| Test | Where | State | Decides | When | Next action |
|---|---|---|---|---|---|
| ETF daily book | own simulator (`daily_book_shadow`) | running since 2026-10-01 | that live signals match the backtest (costs are modeled, not measured) | ongoing | make the core-book decision first (below), then move the decided book to its own Alpaca paper account: fractional shares remove the whole-share misweighting and give broker fills |
| LLM fundamentals | `data/llm/fundamental_scores` | **1 of 12 runs** (Oct only) | PASS/KILL on 1-month rank IC | after 12 monthly runs | the November run is due; months can't be back-filled. Schedule it monthly |
| Forecast journal | `data/journal` | first run 2026-11-05 15:00 | calls and ideas PASS/KILL | 60 run days (~Feb 2027), 120 (~May 2027) | keep the PC on at 15:00 with Claude logged in; Gateway for live quotes |
| AI competition | Alpaca `PA31SWJZFFPD` | starts 2026-11-05 | nothing about skill (8 weeks, a month late, high-risk sizing); it's a plumbing test and the contest entry | 2026-12-31 | check `agents.competition status` after the first trades |
| Scanner log | `data/live/scanner` | **broken: 1 capture since Oct 1** | whether IBKR's live scanner finds ORB's pick | ~3 months of captures | needs Gateway up at 09:25 (mini PC + IBC) |
| ORB top-1 | IBKR paper (`orb_live`) | built, never run | does ORB survive real fills (backtest Sharpe ~0.7)? | ~6 months of paper | after Gateway is reliable: `--what-if` first, then paper. IBKR only (needs the scanner) |
| Large-cap momentum | not built | candidate | is the 2022-26 result more than one bull market? | backtest first | validate on 2016-2021 (one month of Massive Developer) before building a live ranker; then an Alpaca account (fractional shares) |
| QQQ noise-area momentum | not built | candidate (picked after SPY failed) | does the post-publication edge persist? | ~6 months of paper | lowest priority; an Alpaca account would do (QQQ only) |

Decisions that need no more data: the core book (momentum + vol-managed as the core; trend
vs risk parity; replace or drop the swing sleeve). Eight more weeks of shadow fills can't tell
these apart; the backtests and robustness grids are the evidence. Parked unless wanted:
Serenity follow-up and the Congress retests (Senate buys, $250k+ buys).
