# Local data inventory, 2026-10-01

This read-only audit supplements [the daily ETF data audit](../qqq_research_cycle/data_audit.md).
It inspects actual cached metadata and implementation, without contacting a broker,
retrieving market data, reading credentials, or changing live settings. The machine-readable
outputs are [inventory.json](inventory.json) and [storage_inventory.csv](storage_inventory.csv).
Reproduce with:

```powershell
.\.venv\Scripts\python.exe research/portfolio_data_review/inventory.py
```

Counts are a local snapshot, not assertions of vendor entitlement or complete historical
coverage. All sizes below use decimal MB/GB. Cached vendor price files remain under ignored
`data/`; these artifacts contain aggregate metadata only.

| Dataset | Actual local coverage | Research capability and gap |
|---|---|---|
| Adjusted daily prices | 574 symbols; 217.84 MB; full per-symbol ranges in JSON | Long ETF history is usable now. QQQ starts 1999; GLD starts 2004. Today's stock cache is not a historical constituent universe. |
| Massive whole-market daily bars | 1,253 trading dates, 2021-10-04–2026-09-30; 433.53 MB | Includes securities that later delisted, but bars are unadjusted and not a dividend or delisting-return database. |
| Massive whole-market minute bars | 1,253 dates, 2021-10-04–2026-09-30; 31.60 GB | Supports current intraday research. Four dates were added since the earlier daily-cycle audit; derived single-ticker caches may still end September 24 until rebuilt. |
| Selected one-second bars | 810,634 rows in 17,994 one-minute windows; 1,235 dates, 2021-10-22–2026-09-24; 1,495 tickers; 115.25 MB | Selected entry/stop windows for ORB/slippage studies, not a complete second-bar market. Columns are timestamp/OHLC/volume/VWAP; no bid, ask, NBBO, quote size, or queue data. |
| Point-in-time market caps | 18,031 rows; 60 dates, 2021-10-29–2026-09-30; 800 tickers/783 CIKs | Roughly 300 historical liquidity candidates per month, not a full historical market-cap universe. 31 rows lack cap/CIK. |
| SEC XBRL company facts | 360 cached company JSON files; 86.09 MB | Original-accession and availability filters support financial statement research for this selected issuer set. Not market-wide coverage. |
| SEC submission indexes | 360 issuer files; 961,924 index records; 19.95 MB | Filing metadata includes forms, accession numbers, filing dates, acceptance timestamps and items. An index entry is not the underlying filing document. |
| Form 4 metadata | 313,199 records across 352 issuers, filing dates 2002-11-13–2026-09-30; 3,520 amendments separately | Acceptance timestamps exist for all indexed records. No transaction XML, parsed transaction codes/prices/shares, or insider signal pipeline is cached. Early min dates do not imply a complete historical Form 4 market. |
| Earnings 8-K Item 2.02 metadata | 17,084 records across 345 issuers, 2004-09-21–2026-09-30 | Acceptance timestamps complete within this index. Useful starting point for post-filing events, not a schedule of earnings dates known in advance. |
| Historical 10-K representation | 2,552 word-count JSON vectors across 341 issuers, filing dates 2019-01-23–2026-09-29; 48.36 MB | Supports existing text-similarity research. These are bag-of-words vectors, not original filing HTML/XML or complete readable text. |
| Recent filing text | 286 cleaned files across 196 issuers, 2026-06-03–2026-09-30; 12.61 MB | 180 10-Q, 90 8-K, 16 10-K records; latest-filing excerpts, not a historical release archive. 196 additional filing-directory indexes use 0.09 MB. |
| LLM fundamental scores | One cohort: 200 scores as of 2026-10-01, universe date 2026-09-30; 42 files/2.36 MB including inputs and batches | A forward-test starting point. No matured monthly return evidence; historical relabeling would be contaminated. |
| Forward execution evidence | Zero `fills.csv` files, no ORB ledger directory; one shadow equity row | Adapter implementation exists; actual execution/slippage evidence has not accumulated. A shadow row is not a broker fill. |
| Scanner evidence | One date, 2026-10-01: nine nonempty snapshots | Eight IBKR scanner lists contain 50 symbols each; one Massive snapshot contains 100. Useful first capture, insufficient for a measured inclusion rate. |
| Congress | 69,403 transactions; filing dates 2014-01-03–2026-09-22; underlying trade dates start 2011-06-20 | Already researched, including known filing lags. Source data and per-filer JSON use 59.06 MB. |
| Social | 6,592 posts and 13,010 mentions; 2025-07-02–2026-09-17 | One person's short, retrospectively collected sample; not an independent broad signal corpus. Whole social cache: 15.88 MB. |

No dedicated local futures contract history, options chains/Greeks/quotes, crypto exchange
spot or perpetual/funding history, historical equity NBBO, historical borrow availability,
or short-interest dataset was found. The daily cache includes `^VIX`, `^GSPC`, and `^SP500TR`,
but index levels and ETF exposures do not supply tradable underlying futures or option
contracts. Saved research-site HTML is likewise not a market-data feed. This is a finding
about this repository, not about what the subscribed account could obtain.

## Consequences for the roadmap

The high-value immediate work is to use the installed daily and intraday architecture while
collecting evidence and fixing data semantics. The paper adapter and shadow runner already
exist, so the roadmap's instruction to build them is stale. The next evidence gap is actual
forward scanner and paper execution observations; no local fill history supports a claimed
spread or fill-rate estimate yet. Paper fills, when available, should remain distinguished
from executable live queue behavior.

The existing SEC helper `earnings_release()` selects the latest 8-K Item 2.02 using
`filingDate < asof`, then retrieves a cleaned exhibit. Although the underlying submission
index retains `acceptanceDateTime`, the helper does not use or return it. Neither timestamp
identifies when an upcoming earnings date was announced. A strategy positioned before an
announcement requires a separately archived schedule with its own announcement timestamp;
an 8-K filing timestamp cannot be used to manufacture that information. A post-filing event
study can instead use acceptance time, conservative dissemination delay, and next-executable
prices. An earnings press release may have been public before the 8-K acceptance.

Insider research can reuse EDGAR access and cached index records, but needs a bounded Form 4
XML ingestion/parser build, accession/owner identities, amendments, derivative versus common
share classification, open-market transaction codes, and availability timestamps. Parsing
metadata alone cannot distinguish an informed purchase from an option exercise, grant,
gift, or scheduled sale. The 360-company coverage was selected through the existing recent
point-in-time universe; it should not be relabeled a historical market-wide insider dataset.

Longer Massive bar history would genuinely extend intraday regime coverage, subject to the
actual plan and retention terms verified separately. It does not automatically extend the
point-in-time stock-selection dataset. `backtest/megacap.py` first chooses the 300 stocks
with highest trailing dollar volume each month, then requests date-specific market cap/CIK
records and retains one share class per company. Earlier research needs those earlier
reference requests, suitable split coverage, ticker-reuse safeguards, and delisting/terminal
return handling. The assertion that 300 liquidity candidates always contain every largest
company is an unverified approximation, not a full historical constituent guarantee.

At the observed compression rate, five additional years of whole-market minute bars would
add about 31.6 GB, plus roughly 0.43 GB for daily bars. This is a planning extrapolation,
not a provider size estimate; older market volume can differ. Leave room for downloads,
conversion scratch space, derived caches, and backups. The workspace drive had about
395.9 GB free at the final metadata check, so the observed scale alone is not a storage
blocker. Date coverage and hashes should be verified before any one-off subscription ends,
and retention rights must be checked rather than assumed from successful downloading.

Diversifying into futures requires more than buying price history: individual contracts,
expiry and roll rules, point/tick values, exchange sessions, settlement/variation margin,
transaction costs, and attainable contract sizes for this account. Continuous adjusted
charts alone do not specify executable P&L. Crypto spot research similarly needs an explicit
venue, fee schedule, timestamp/session policy and USD funding convention; perpetuals also
require funding and liquidation modeling. Options add historical chain coverage, bid/ask,
expiry/corporate actions and exercise/assignment logic. None of those engines currently
exists locally. With the stated sub-$100 monthly budget plus occasional one-off purchases,
the inventory supports prioritizing one falsifiable data extension at a time, not simultaneous
subscriptions across all three new asset classes.

Provider prices, entitlements, legal availability and contract costs require current external
verification; this offline inventory does not quote or endorse a purchase.
