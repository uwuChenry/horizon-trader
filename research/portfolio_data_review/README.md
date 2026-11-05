# Portfolio research and data priorities — 2026-10-01

**Recommendation: investigate a portfolio of the existing daily core, ORB and QQQ
noise strategies before buying another signal feed.** The measured correlations
support that direction. A Sharpe below one is not a reason to discard a strategy
that improves the whole portfolio after costs. However, the existing combined
returns have not been reproduced in a single account with shared positions,
minimum commissions and margin limits. That is the highest-value next experiment.

This review reads [the roadmap](../roadmap/README.md), [CLAUDE.md](../../CLAUDE.md), prior
experiment notes and saved results; inventories the actual caches; replays existing
strategies; and checks current data products against the owner's **under $100/month,
occasional one-time purchase** budget. It supplements the completed
[first research cycle](../qqq_research_cycle/README.md), whose daily ETF candidates did
not satisfy both objectives. That negative finding does not establish that leverage
on QQQ is the only useful research direction.

## Why combining modest strategies can work

For N equally risky strategies with the same true net excess-return Sharpe S and
common pairwise correlation rho, equal risk allocation gives:

`portfolio Sharpe = S * sqrt(N / (1 + (N - 1) * rho))`.

Three strategies with Sharpe 0.7 give portfolio Sharpe **1.21** at zero correlation,
**0.96** at correlation 0.3, and **0.82** at correlation 0.6. This is an illustration,
not an estimate for this repository. It assumes stable expected returns, costs and
correlations. Selecting three historical winners invalidates that interpretation.

For a small addition under linear costs, a useful marginal condition is
`new sleeve Sharpe > correlation_with_portfolio * portfolio Sharpe`. The relevant
question is contribution to the existing portfolio. Distinct data sources can still
produce the same semiconductor, equity momentum, short-volatility or liquidity
exposure. Measure net P&L correlation, downside co-movement, market beta and the
effect of removing each sleeve. Leverage raises exposure; it does not independently
create a higher excess-return Sharpe and financing can reduce it.

## What the new replay actually shows

Primary comparisons share **2021-11-02 through 2026-09-24**, with initial NAV on
2021-11-01: 1,228 sessions, $5,000 standalone starts and IBKR **Fixed** modeled
commissions. QQQ uses dividend-adjusted total returns on those same dates. The
original saved ORB baseline replays with **zero dollar discrepancy** at every NAV.
No tuned ORB cutoff/relative-volume variant was substituted for that baseline.

| Stream or arithmetic screen | Full CAGR | Full maximum DD | Full excess Sharpe | Reused 2024+ excess Sharpe |
|---|---:|---:|---:|---:|
| QQQ total return | 14.87% | -35.12% | 0.55 | 0.96 |
| Daily core | 6.35% | -10.42% | 0.32 | 0.79 |
| ORB baseline | 8.24% | -22.99% | 0.31 | 0.47 |
| QQQ noise | 15.13% | -17.11% | 0.82 | 0.64 |
| Standalone risk parity | 6.50% | -18.14% | 0.31 | 1.02 |
| Frozen inverse-volatility screen | 9.72% | -5.02% | 0.83 | 1.12 |
| Daily + QQQ noise return sum | 22.51% | -10.64% | 1.14 | 1.25 |
| Daily + 0.25 ORB + 0.5 noise screen | 17.02% | -8.92% | 1.09 | 1.40 |
| Same reduced screen, additional slippage | 15.38% | -9.11% | 0.96 | 1.29 |

**The combination rows are screening arithmetic, not executable portfolio
backtests.** They scale net returns from separately capitalized accounts, which
also scales already-paid minimum commissions. Real $5,000 account orders do not
scale this way. Same-ticker netting, discrete shares, overlapping margin use, short
availability, missed stop-limit fills and financing remain unresolved. A gross
exposure ceiling inferred by adding sleeve limits is not verified buying power.
QQQ noise alone can request 4x exposure. Daily closing drawdowns can also miss
larger intraday losses. These rows cannot certify the original return/drawdown target.

The unlevered-weight screen freezes inverse standalone volatility weights estimated
on 2021–2023: **51.60% daily core, 20.33% ORB, 28.07% noise**. The full-period result
includes that fitting period. The reduced overlay uses fixed illustrative scales;
no search for the best allocation was run. The cost stress adds one cent per share
to each ORB fill and raises noise's non-auction slippage from half a cent to one cent.
It still does not establish realistic auction fills or rejected-order behavior.

Sharpe uses daily returns less one common lagged DFF cash hurdle, annualized with
sqrt(252), sample standard deviation. Idle source cash earns zero; we do not add
Treasury interest separately for each intraday strategy. CAGR uses actual calendar
years. The saved metrics include excess Sortino using RMS downside deviations over
all sessions, drawdown duration in calendar days and separate development/reused
test/regime results. Standalone fills and fees are saved; aggregate executed
exposure, turnover and trade counts for synthetic blends are **unavailable until
the account replay**, rather than sums presented as real account activity.

The principal evidence is complementarity: daily core correlation is **+0.051 with
ORB** and **-0.048 with noise**, versus **0.74 with risk parity**. Core/ORB and
core/noise correlations remain near zero in 2022 (+0.020/+0.025). During QQQ
drawdowns deeper than 10%, they are +0.051/+0.127. Winners momentum has roughly
0.70 correlation with the core on its shorter sample; its Tiered costs, fractional
shares and price-only returns also prevent an equivalent primary comparison.

The old **1.690691** daily-plus-noise Sharpe is reproducible from the saved Tiered
streams. It falls to **1.439242** after one cash hurdle, and to **1.137518** using
the Fixed replays. That explains the older attractive number without treating it
as achievable account performance.

Uncertainty is substantial. For the reused 2024+ period, the frozen screen's 1.12
Sharpe has a **95% block-bootstrap interval of 0.18–1.99**. The reduced overlay's
Sharpe improvement over the core is +0.62, interval **-0.28 to +1.34**. These paired
21-session blocks/1,000 draws preserve common dates but do not correct the large
prior research search or execution-model errors. Nine portfolio constructions,
including three delete-one controls, are recorded. **No history here is untouched.**

The return/drawdown tradeoff remains visible in the later period. A higher Sharpe
does not imply a higher CAGR than QQQ:

| Reused 2024+ period | CAGR | Maximum DD |
|---|---:|---:|
| QQQ total return | 24.84% | -22.77% |
| Daily core | 11.91% | -10.42% |
| QQQ noise | 13.75% | -17.11% |
| Frozen inverse-volatility screen | 13.28% | -4.86% |
| Daily + QQQ noise return sum | 27.39% | -10.64% |
| Reduced overlay screen | 23.75% | -8.92% |
| Reduced overlay, additional slippage | 22.00% | -9.11% |

The reduced overlay therefore falls short of QQQ's later-period return even in
screening arithmetic. The uncapped daily-plus-noise sum is attractive on paper but
is especially exposed to the unresolved joint-margin issue.

QQQ noise's standalone CAGR edge over QQQ is only 0.26 percentage points; its
one-cent case drops to **14.19%**, below QQQ. This is a fragile modeled pass on this
short period, not evidence that the original objective has been solved.

## Data already on disk

| Data | Actual coverage | Most consequential limitation |
|---|---|---|
| Daily adjusted prices | 574 symbols; QQQ starts 1999 | Today's stock list is not a historical stock universe |
| Massive market-wide minute/daily bars | 1,253 dates, 2021-10-04–2026-09-30; 31.60 GB minutes | Raw flat files are unadjusted; no historical NBBO |
| Selected second bars | 810,634 rows, 17,994 selected one-minute windows | ORB entry/stop selection; OHLCV is not quote or queue history |
| Historical market caps | 18,031 rows, 60 monthly dates, 800 tickers | Starts October 2021; constructed from 300 liquidity candidates/month |
| SEC submissions and company facts | 360 issuers; 961,924 filing-index records | Selected issuer sample, not market-wide historical coverage |
| Form 4 / earnings 8-K metadata | 313,199 Form 4 records / 17,084 Item 2.02 records | No insider transaction XML; no advance earnings calendar |
| Text/LLM | 2,552 10-K word-count vectors; 286 recent cleaned filings; one score cohort | No matured LLM forward results; no valid backward relabeling |
| Execution evidence | No fills.csv or ORB fill ledger; one shadow equity row | Adapter code exists, measured forward fill evidence does not |
| Futures / options / crypto | No dedicated contract/chain/venue datasets | New ingestion and accounting required |

The [full inventory](local_data_inventory.md) includes ranges, sizes, scanner,
Congress and social caches. Four newer market-wide dates are present, while the
derived QQQ research cache still ends September 24; those extra dates were not
silently mixed into the comparison. Another five years of minute history would
use approximately **32 GB** at current compression, plus working space and reference
data. Storage is currently sufficient; valid timestamps and instrument histories
are the more important constraints.

## Ranked hypotheses and what would reject them

| Rank | Hypothesis and plausible mechanism | Bounded next test | Falsification / rejection |
|---|---|---|---|
| 1 | Daily premia and intraday flow/trend respond to different horizons; their low observed covariance survives real accounting | One shared-account replay of frozen inverse-vol weights and the reduced overlay; core and QQQ controls | Increment disappears after minimum fees, netting, margin constraints, delayed fills or added history |
| 2 | Cross-asset futures trend, later carry, adds rates/FX/commodity risks beyond the equity book | First one fixed 12-month trend rule across a predefined liquid panel; carry only after contract/roll validation | Benefit is equity beta, a few crisis trades, implausible rolls, or impossible whole-contract sizing |
| 3 | Public insider open-market purchases contain slowly incorporated issuer information | One Form 4 transaction parser and fixed cluster-buy event study with release-time entry | No incremental net return versus sector/size/momentum controls, concentration in untradeable names, or effect vanishes after filing delay |
| 4 | Options surface information helps size stock/ETF exposure | Small SPY/QQQ historical EOD-chain pilot; freeze one feature before labels | Improvement disappears with stale-quote filters, lagged features, basic realized-vol controls or later validation |

Futures trend is motivated by the cross-market evidence in
[Moskowitz, Ooi and Pedersen](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum).
The behavioral interpretation is gradual adjustment to information; it is a
hypothesis, not an assurance of persistent alpha. Carry has a distinct term-structure
input but can compensate for crash/liquidity risk; use the
[authors' research and data](https://www.koijen.net/research.html) for an initial
mechanism check, not as small-account executable returns. Free published factor
series can screen overlap before buying contracts.

The insider hypothesis follows
[Cohen, Malloy and Pomorski](https://www.nber.org/papers/w16454), whose distinction
between routine and opportunistic trades argues against treating every filing as
an informed purchase. Historical publication returns are not expected returns for
today's large-cap sample. Start with free SEC infrastructure rather than a paid
sentiment feed. [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
provide filings infrastructure, not a ready-made validated insider strategy.

Options-derived information and trading option risk premia are separate research
projects. Start with the former. Selling volatility can produce a high historical
Sharpe while worsening precisely the equity crashes we want to reduce. Additional
data origins alone do not resolve that portfolio risk. Crypto likewise needs
measured stress correlation; the roadmap's claim that it is the most uncorrelated
addition is not established by this repository.

## Purchases ranked against the budget

Prices checked 2026-10-01, USD before tax; plan entitlement is not inferred from
the files on disk. These are alternatives, not a shopping basket.

| Priority | Data and current price | Decision |
|---|---|---|
| First, $0 incremental data | Existing caches; SEC transaction documents; forward quote/order logging | Fix shared-account accounting and measure execution before expanding the strategy search |
| First paid extension | **Massive Stocks Developer, $79/month**, ten years of minute/second/trade history | Best direct validation of existing ORB/noise. Roughly late 2016 onward as of now; not 2008, not guaranteed all of 2016. Backfill corporate actions and monthly point-in-time references too |
| Alternative research branch | **Norgate Futures, $148.50/6 months or $270/year** ($24.75/$22.50 monthly equivalent, prepaid) | Best publicly priced long daily cross-asset panel. New futures accounting needed; no new intraday edge assumed |
| Targeted one-off supplement | **Databento historical usage pricing; basket quote required** | Selected CME contracts/settlements/definitions, then quote windows for execution; do not subscribe to the $199/month plan under this budget |
| If stock selection becomes the priority | **Norgate US Stocks Platinum, $346.50/6 months or $630/year** | Includes delisted names and historical constituents back to 1990; cheaper tiers do not solve survivorship |
| Defer | **Cboe EOD SPY/QQQ chains, price unverified** | Request a precise full-chain history/sample quote before deciding affordability; no mass options purchase yet |

Sources: [Massive stocks pricing](https://massive.com/pricing?product=stocks),
[Norgate futures](https://norgatedata.com/futurespackage.php),
[Databento pricing](https://databento.com/pricing),
[Norgate stocks](https://norgatedata.com/stockmarketpackages.php),
[Cboe EOD product](https://datashop.cboe.com/option-eod-summary).

Massive Developer plus annual-equivalent Norgate Futures is **$101.50/month** before
broker feeds, so buying both concurrently exceeds the stated cap. Massive Starter
plus the futures annual equivalent is $51.50/month, before other expenses, but that
does not establish permission to retain older Developer-only data after downgrading.
Keep the existing broker-data bill inside the ongoing budget. The historical
performance above excludes research subscriptions and infrastructure: $79/month
alone is $948/year, or **19% of an initial $5,000 account**. Research spending may
be funded separately; it is still a substantial operating hurdle if charged to
that trading account.

Important product distinctions:

- Massive stock flat files are
  [unadjusted](https://massive.com/docs/flat-files/stocks/overview). Its adjusted
  aggregates handle splits, [not dividends](https://massive.com/knowledge-base/article/is-massives-stock-data-adjusted-for-splits-or-dividends).
  Longer bars alone do not produce stock total returns or extend our historical universe.
- Cheap Massive options plans list Greeks, but the
  [chain snapshot endpoint](https://massive.com/docs/rest/options/snapshots/option-chain-snapshot)
  has no historical snapshot parameter/history entitlement. Current IV/OI cannot
  backfill historical signals. A usable pilot needs past bid/ask chains, simultaneous
  underlying prices, expiries, adjusted deliverables and known OI availability.
- A one-month download is not automatically a permanent archive. Massive's
  [termination terms](https://massive.com/legal/market-data-terms-of-service) require
  ceasing use/deleting data after specified account termination/restriction events;
  downgrade rights for older history need clarification. Norgate explicitly requires
  deletion of exported raw data and metadata after expiry without imminent renewal,
  while allowing original research results to remain: [licensing FAQ](https://norgatedata.com/faq.php).

The [futures/options vendor note](vendor_futures_options.md) specifies exact pilot
baskets, required contract metadata, history limitations and quote requests.
Futures must use actual-contract P&L and rolls, collateral cash once, integer
contracts and realistic margin; continuous-chart percentage returns are insufficient.
Smaller contract availability is changing, but native history, broker availability
and spreads must be verified before claiming feasibility at $5,000.

## Corrections to the roadmap and next evaluation protocol

1. **8-K acceptance is not an advance earnings calendar.** It can support a
   post-filing strategy after dissemination delay; the underlying press release
   may already have been public. The current helper uses filing date, despite raw
   acceptance timestamps being cached. Pre-announcement trading needs a separately
   timestamped schedule. The [SEC's 8-K guide](https://www.sec.gov/files/readan8k.pdf)
   explains that filings can follow the event.
2. Form 4 metadata is not parsed transaction data. Distinguish purchases from
   exercises/grants/gifts, amendments and derivative securities; train any routine
   trader classification only on then-available prior filings.
3. FINRA short interest must enter features on its publication date, not settlement
   date. FINRA publishes on the seventh business day after the reporting settlement
   date; short volume is a different dataset. [Official coverage/timing](https://www.finra.org/finra-data/browse-catalog/equity-short-interest).
4. The broker adapter already exists. The next gap is timestamped scanner, decision,
   bid/ask, order, cancellation and fill evidence. Paper trading is an operational
   test: IBKR simulates top-of-book fills and complex orders, so it cannot establish
   queue position or live stop-limit fill rates. [IBKR paper limitations](https://www.ibkrguides.com/clientportal/aboutpapertradingaccounts.htm).
5. Older Massive data would be **new to this repository**, not necessarily untouched
   by the published research that motivated these signals. Preserve that distinction.

The next account experiment should freeze the existing three signals and just two
allocation rules above. Use 2021–2023 for plumbing and risk estimates, reused 2024+
for historical confirmation, and inspect any newly acquired older regimes once
after freezing. Do not tune against that batch. Future observations after the
freeze provide prospective evidence; a few weeks of paper results cannot establish
Sharpe above one. Any strategy changed after a test gets a new version and ledger row.

Use one NAV, raw shares, explicit dividend/corporate-action cash flows, one cash
balance, netted orders, actual minimum fees and conservative financing/short costs.
Reserve buying power for concurrent orders and apply verified account restrictions.
Report both $5,000 implementation and a separately labeled capital sensitivity;
do not silently replace the owner's account with a larger one to improve costs.

Controls: QQQ total return on identical dates, daily core, intraday sleeves alone,
exposure-matched QQQ/cash and a fixed volatility-managed QQQ baseline. Evaluate
signal contribution by removing each sleeve, along with the added return from
leverage. Prespecify one-/five-minute intraday execution delays, next-session delay
for daily orders, higher spread/slippage, no-short/missed-fill cases, and separate
2022 and older crisis regimes. Record rejected orders and turnover from executions.

The original objective stays **higher net CAGR than QQQ and maximum drawdown
magnitude no greater than 90% of QQQ's**. Require it on the designated validation
period without violating account constraints, and require the portfolio benefit
not to disappear under the cost/delay stresses. Also report contribution when the
absolute objective fails: an independently useful risk reducer need not beat QQQ
standalone. Sharpe above one is an aspirational diagnostic, not a parameter-search
stopping rule. Broad intervals or failed stress cases mean further research, not
promotion to a proven market-beating strategy.

## Reproduce and inspect

Run from repository root with the existing environment and local caches:

```powershell
.venv\Scripts\python.exe research/portfolio_data_review/inventory.py
.venv\Scripts\python.exe research/portfolio_data_review/analyze_portfolio.py
.venv\Scripts\ruff.exe check research/portfolio_data_review
```

Artifacts: [diagnostic conventions](diagnostic_notes.md),
[offline correlation/equity/drawdown figures](correlation_heatmap.html),
[all metrics](results/metrics.csv), [experiment ledger](results/experiment_ledger.csv),
[daily return panel](results/returns.csv),
[incremental Sharpe intervals](results/incremental_sharpe.csv),
[source manifest](results/manifest.json), and [data inventory](inventory.json).
These scripts make no broker calls or network requests. No paid data was purchased
and no live settings were changed in this follow-up.

Verification: both scripts pass Ruff. Replaying with the saved effective settings
reproduced the metrics unchanged; the original ORB NAV comparison remained exact.
An independent check verified 39 input/code hashes, local document links, all
1,228 common sessions, 25 unique ledger entries and CAGR calculations directly
from the saved daily returns. This verifies reproducibility of the screen, not
the accuracy of its inherited execution assumptions.
