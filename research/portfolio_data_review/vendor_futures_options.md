# Futures and options data: official-source review

Verified **2026-10-01**. Budget: under $100/month, with occasional one-off purchases.
No account was opened, purchase made, paid dataset downloaded, or broker setting changed.
Prices below are public USD prices; taxes, eligibility and requested-data quotes remain
unverified. Research requirements and ranking below are our engineering judgment.

## Recommendation within this budget

**Norgate is the strongest publicly priced option for broad, long daily futures research;
Databento is the targeted one-off alternative and execution-data supplement.**
Daily trend/carry research needs individual contracts, settlements and metadata, with
more granular data reserved for execution checks. A continuing Databento $199/month
subscription does not fit the budget. **Cboe EOD option chains are conditional:**
the data product is relevant, but its configured purchase price was not publicly
verifiable in this session. Do not commit to an options research purchase without that
quote and a sample-quality check.

| Priority | Concrete quote request | Purpose and unresolved dependency |
|---|---|---|
| 1A | Norgate Futures: $148.50/6 months or $270/year, paid for the term | Broad daily cross-asset history, including older crises; validate each proposed contract's actual start date. Requires ongoing subscription for raw-data retention. |
| 1 | Databento `GLBX.MDP3`, parents `ES.FUT`, `NQ.FUT`, `ZN.FUT`, `6E.FUT`, `GC.FUT`, `CL.FUT`; 2010-06-01 inclusive to 2026-10-01 exclusive; separately quote `statistics`, `definition`, and `ohlcv-1m` | Equity/rates/FX/gold/oil trend and term-structure research. Include all expiries, then retain outright contracts and at least the front three liquid maturities. Quote size before downloading; use statistics-only first if minute bars exceed the one-off budget. |
| 2 | Native `MES.FUT` and `MNQ.FUT` from 2019-05-06, `MGC.FUT` from 2010-10-04; definitions/statistics, plus `mbp-1` on selected recent sessions, stress sessions and roll windows | Test actual smaller-contract spreads and discrete sizing. Parent contracts can supply earlier signal evidence, but cannot supply historical micro fills. Do not download years of full-market order books. |
| 3 | Cboe Option EOD Summary: SPY and QQQ, 2012-01-01 through 2026-09-30, all listed strikes/expiries on each date; two separate quotes, with and without Calcs | Daily defined-risk option research. Ask price per underlying, full-history cap if any, expired-series inclusion, and ongoing update cost. No verified quote means affordability remains unknown. |

These requests are specifications, not purchase instructions. A small sample should pass
contract coverage, timestamp, stale-quote, multiplier and settlement reconciliation checks
before a larger order. The Databento futures panel omits 2008; it cannot substantiate a
financial-crisis result without a separately sourced older history.

## Norgate: long daily history with ongoing access obligations

The Futures package is **$148.50 for six months** or **$270 for twelve months**:
equivalent to $24.75 or $22.50/month, but payable for the full term. It covers around
100 selected markets across 11 exchanges/groups, with history generally reaching
around 1980 or market inception. It includes individual contracts and unadjusted/
arithmetically adjusted continuous series; closes are generally official settlements.
Its default cash-settled roll is the business day before final trading, and deliverable
roll is before first notice. For research, use individual contracts and evaluate
earlier liquidity-based rolls rather than assuming that default is executable.
[Futures package and prices](https://norgatedata.com/futurespackage.php).

This is **not a one-time purchase of a permanent raw archive**. Upon expiry without
imminent renewal, exports, normalized rows, point-in-time snapshots, metadata and
backups must be deleted; original research results and algorithms can remain. Thus
future raw-data replay requires a maintained subscription. Personal-use processing on
other systems is permitted while subscribed. [Licensing FAQ](https://norgatedata.com/faq.php).

The annualized amount fits a sub-$100 data budget alone. A $79/month service plus this
$22.50/month equivalent totals **$101.50/month**, so that combination exceeds the stated
cap before other services. Choose the data package for the next experiment rather than
automatically stacking subscriptions.

## Databento: coverage, cost and access

`GLBX.MDP3` covers CME/CBOT/NYMEX/COMEX futures and options on futures from **June 2010**.
The source protocol differs before May 2017, so “16 years” does not imply identical
native order-by-order information throughout. Official settlements, cleared volume and
open interest are in `statistics`; publication can be later than the economic trade
date. Use publication timestamps for features, particularly open-interest roll rules.
[Dataset documentation](https://databento.com/docs/venues-and-datasets).

Historical CME data is advertised **from $0.50/GB**, a floor rather than a quote for every
schema. [Official futures catalog](https://databento.com/futures). Usage-based historical
access requires no subscription. CME Standard currently advertises **$199/month**;
included history differs by schema. New teams are advertised **$125 historical-data
credits**, expiring six months after signup; existing-account eligibility is unknown.
Billing uses uncompressed binary size, so compression does not reduce the charge.
Batch requests can be downloaded again for 30 days without another charge; repeated
streaming requests should not be assumed free. [Pricing](https://databento.com/pricing).

Use `metadata.list_unit_prices` and `metadata.get_cost` for each explicit symbol/schema/date
request, then preserve the quote with the eventual input manifest. The latter returns
USD and incorporates plan discounts; non-10-minute boundaries can overestimate, and
definition quotes require whole-day boundaries for accuracy. Actual transmitted bytes
determine billing. Metadata access is free, but an API key is required; no authenticated
quote was obtained here. [Historical API](https://databento.com/docs/api-reference-historical?historical=http).

`ohlcv-1d` uses UTC dates and trade-based aggregation, not exchange trading sessions or
official settlement. Prefer `statistics` for settlement marks and aggregate minute bars
to the intended session for signals/execution. MBP-1 includes changes at the best bid/ask;
TBBO accompanies trades with the preceding BBO, so it does not capture every quote update.
Daily bars cannot establish a stop fill or executable spread.
[Schema conventions](https://databento.com/docs/knowledge-base).

Continuous symbols map to actual contracts and are **not back-adjusted**. Save contract
identities and roll mappings; book exit and entry costs explicitly. Calculate futures
cash P&L from contract price differences and dollar point value, not percentage changes
across a stitched price series. Negative prices require valid accounting. A fixed roll
schedule, or prior-published liquidity rule, must be chosen before testing.
[Futures conventions](https://databento.com/docs/examples/futures/futures-introduction/special-conventions-for-futures-on-databento).

Required companion records: symbol/instrument mappings, expiry and first-notice dates,
cash versus physical settlement, exchange sessions/holidays, currency, tick size and
dollar point value, volume/OI publication time, settlement revisions, and historical
margin/fee assumptions. Cross-check dollar point values against CME specifications:
Databento's `unit_of_measure_qty` needs special treatment for some CBOT instruments;
field names alone are unsafe. [Tick-value guidance](https://databento.com/blog/tick-sizes-and-values).

## Contract granularity and native history

MES and MNQ began **2019-05-06**, with respectively **$5** and **$2 per index point**.
[CME micro FAQ](https://www.cmegroup.com/articles/faqs/frequently-asked-questions-micro-e-mini-equity-index-futures.html),
[product overview](https://www.cmegroup.com/education/courses/micro-e-mini-futures/micro-e-mini-futures-products-overview).
MGC began trade date **2010-10-04**, representing **10 troy ounces** and physical delivery;
it is not a 2019 launch. [CME launch announcement](https://investor.cmegroup.com/news-releases/news-release-details/cme-group-announces-launch-e-micro-gold-contracts).

**Current development:** E-nano equity contracts launched **2026-08-24**, one tenth the
micro size: S&P **$0.50/point**, Nasdaq **$0.20/point**. They may improve $5,000-account
sizing, but offer only weeks of native history. Databento instrument availability,
IBKR access, commissions, liquidity and spreads still require verification; scaled
historical ES/NQ prices are a proxy, not a nano execution backtest.
[CME listing notice](https://www.cmegroup.com/notices/market-regulation/2026/08/msn08-19-26.html),
[current contract FAQ](https://www.cmegroup.com/articles/faqs/faq-e-nano-equity-index-futures.html).

Size research positions by full notional exposure, point-value losses under stress,
and available account equity. A low intraday margin requirement is not a loss budget.
Whole-contract rounding can make a diversified futures portfolio impractical at $5,000;
the research should be permitted to reject it on that basis.

## CME free settlement access is limited in purpose

Public website settlement values are freely viewable after **midnight US Central**.
That availability is too late for a signal assumed known at the preceding close.
The current FAQ quotes DataMine End of Market subscriptions at **$105/month**, **$105
per month per exchange**, or **$2,100/month**, depending on product. It does not establish
a free, complete historical archive. [Current access FAQ](https://www.cmegroup.com/articles/faqs/access-to-cme-group-settlement-data-faq.html).
Historical end-of-day data back to product inception is described as purchasable;
an exact requested-history quote is needed. Free website viewing is useful for spot
reconciliation, not a substitute for licensed historical contracts/quotes.
[Settlement dataset FAQ](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457224332/Settlements%2BFAQ).

## Cboe DataShop: what its option products actually provide

EOD Summary supplies **full option-series cross-sections at two snapshots**, 15:45 ET
and product-dependent close, with NBBO and sizes. It also supplies daily trading
summaries and open interest. Optional **Calcs** supplies IV/Greeks at 15:45, not an
all-day Greek history. Stocks, ETFs and index options are covered; futures options are
excluded. Stock/ETF underlying quotes are included; index underlying quotes have
separate licensing conditions. The product advertises history from **January 2012**.
Public purchase controls select symbols, dates and extras; a usable configured price
was not exposed, so no $/symbol/year estimate is asserted.
[EOD product](https://datashop.cboe.com/option-eod-summary).

There is an official inconsistency: the FAQ says EOD/interval history starts in
**January 2010**, while the product pages say 2012. Budget and design around 2012 until
2010-11 delivery is confirmed. Open interest is the previous night's OCC value, static
during the day. Half-day “1545” fields actually refer to 12:45 ET. Nonstandard roots can
represent adjusted deliverables, so do not hard-code 100 shares for every contract.
[DataShop FAQ](https://datashop.cboe.com/faqs).

Option Quotes supplies 1-minute or custom-interval snapshots, with optional OI and Calcs.
Effective **2026-06-22**, quote size is captured at the latest **price change** in an
interval; earlier history used the latest price/size update. This is a material break
for size/liquidity filters. Its exact configured price was also not verified.
[Interval product](https://datashop.cboe.com/option-quote-intervals).

For daily research, full-chain snapshots permit selecting contracts that existed on
the decision date. They do not prove intraday stops or midpoint execution. Require
known bid/ask sizes, conservative leg execution, stale/zero-quote rejection, expiry and
exercise/assignment rules, corporate-action deliverables, underlying dividends, and
fees per leg. Quotes and optional model Greeks do not remove these accounting tasks.
