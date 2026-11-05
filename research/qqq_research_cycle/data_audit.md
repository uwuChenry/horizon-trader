# Data and prior-research audit, 2026-10-01

The practical first-cycle choice is daily ETF research. It offers long histories,
fully observed tradable instruments, simple next-open execution, and substantially
less ambiguity than the repository's intraday fill studies. Current holdings and
live settings were not changed.

## Available data

The ordinary `data/bars/` cache contains 574 per-symbol adjusted daily OHLCV files.
`datasources/yf_source.py` requests `auto_adjust=True`; `store.py` replaces full
history on a stale-cache refresh. Research therefore reads the cache directly and
freezes inputs, rather than calling the automatic refresh path during an experiment.

| Instrument | First date | Last date | Rows |
|---|---|---|---:|
| QQQ | 1999-03-10 | 2026-09-30 | 6,933 |
| SPY | 1993-01-29 | 2026-09-30 | 8,475 |
| GLD | 2004-11-18 | 2026-09-30 | 5,500 |
| IEF | 2002-07-30 | 2026-09-30 | 6,082 |
| TLT | 2002-07-30 | 2026-09-30 | 6,082 |
| SMH | 2000-06-05 | 2026-09-25 | 6,617 |
| SOXX | 2001-07-13 | 2026-09-25 | 6,338 |
| SOXL | 2010-03-11 | 2026-09-25 | 4,162 |
| DBC | 2006-02-06 | 2026-09-30 | 5,195 |

QQQ, SPY, GLD, IEF, TLT, SMH, SOXX, SOXL, UUP, and DBC each have zero duplicate
dates, missing OHLC values, nonpositive OHLC values, or inconsistent OHLC envelopes.
SPY/GLD/IEF/TLT/IWM/EFA/EEM/VNQ/DBC have no missing dates relative to QQQ within
their own available intervals. This checks cross-instrument calendar consistency,
not an independent exchange calendar or correctness of every vendor observation.
QQQ's full history permits a separate dot-com stress test; a GLD strategy cannot
be honestly tested in that regime without a proxy. SHY, BIL, SGOV, QLD, and TQQQ
are absent from this adjusted daily cache.

The Massive store contains 1,253 whole-market daily files from 2021-10-04 through
2026-09-30 (0.434 GB) and 1,249 whole-market minute files through 2026-09-24
(31.473 GB). These are unadjusted bars including delisted names, not a dividend
total-return database. Monthly point-in-time market caps contain 18,031 rows;
reference ticker and split files contain 11,938 and 27,663 rows respectively.
The stock-momentum notes document ticker reuse (BNY/SPCX) and require missingness
guards. Current-universe yfinance stock screens remain survivorship biased.

Derived QQQ minute data contain 485,320 rows across all 1,249 dates: 1,239 sessions
with 390 bars, ten half-days with 211 bars. The extra 13:00 bar is trimmed by
`make_bars` to 210 minutes. No duplicate timestamps, date/time-zone mismatch,
nonpositive price, or inconsistent OHLC envelope was found. Timestamps are
America/New_York bar starts. SPY has four missing minutes on one session; its
simulator fills missing minute prices using the preceding close. This approximation
must not be mistaken for an observed executable fill. QQQ's minute last close
differs from its raw daily close by -18.45 to +22.41 bps; minute last print and
official closing auction are distinct observations. Orders intended for the
auction must meet its submission deadline.

The intraday studies have already explored hundreds of variants, including the
480-configuration ORB grid, QQQ noise momentum, execution assumptions, and combined
overlays. The narrow-stop ORB chronology ambiguity and stop-limit fill uncertainty
make a new intraday headline less defensible than daily research in this cycle.

## Dividend, split, and funding checks

The old adjusted cache did not preserve raw prices or corporate actions. A free
Yahoo retrieval using `auto_adjust=False, actions=True` was therefore saved to a
new isolated `data/research_cycle_2026_10_01/raw/` directory. It did not overwrite
existing data. Scripts `fetch_raw.py` and `prepare_inputs.py` reproduce retrieval
and freezing. The frozen `inputs/{QQQ,GLD,IEF}.parquet` columns are:

`adjusted_open`, `adjusted_close`, `raw_open`, `raw_close`, `dividend`, `split`.

Signals and returns use the pre-existing adjusted cache. Nominal share sizing and
fees use the separately retrieved raw history. Yahoo's historical OHLC is split
adjusted, so prices are multiplied by the product of strictly subsequent splits
to recover contemporaneous nominal share prices. QQQ has one split, 2:1 on
2000-03-20; GLD and IEF have none. Thus the primary 2007+ evaluation requires no
split-price reconstruction. There are 90 QQQ dividend events, 290 IEF events,
and none for GLD. None has capital-gain distribution events in the retrieved data.

Fetched adjusted close agrees with the existing cache to maximum relative
difference 0.000118% for QQQ, 0.000199% for IEF, and exactly for GLD. Over 2007+,
compounding `(raw_close + dividend) / previous_raw_close - 1` differs from the
cached adjusted-return terminal wealth by only -0.00343% for QQQ and -0.00169%
for IEF. The largest one-day difference is 0.71 bp QQQ / 0.49 bp IEF, consistent
with vendor precision and adjustment/reinvestment conventions. This supports
the adjusted series as a gross-dividend total-return benchmark, while leaving
vendor-methodology uncertainty explicit.

Using adjusted prices as nominal share prices would materially distort historic
share-based fees and whole-share rounding: at the start of 2007 raw/adjusted
close was 1.1686 for QQQ and 1.6549 for IEF. The frozen separate raw-price columns
prevent that error. Dividend withholding is excluded consistently from candidate
and benchmark returns; user-specific after-tax returns can differ. Ideal dividend
reinvestment implicit in adjusted prices is not a model of discrete dividend
payment dates, cash crediting, or whole-share dividend reinvestment.

`data/reference/dff.parquet` provides 26,384 daily Fed funds observations from
1954-07-01 through 2026-09-24, column `ff` in fractional annual units. It is frozen
alongside price inputs. The final known rate is carried through the six calendar
days to September 30, disclosed in the manifest; no future observation is used.
`tb3ms.parquet` provides monthly observations through August 2026, but a T-bill
yield is not automatically cash interest available in the owner's small account.

The raw and frozen input manifests record SHA256 hashes, date ranges, source
paths, and retrieval/freeze timestamps. Vendor files remain git-ignored.

## Prior-use limits and bounded hypotheses

There are 89 prior saved result bundles, with many 2024+ windows labeled
`oos_start` despite repeated subsequent research. The daily book was already
evaluated through September 2026, as were ETF leverage, daily momentum, risk
parity, and various stock/intraday approaches. A few newly available September
sessions are insufficient for a meaningful final holdout. The proposed 2007-15
development / 2016-20 validation / 2021-26 confirmation windows are chronological
reused-history tests, never an untouched final holdout.

The useful shortlist is: (1) QQQ trend gating to reduce prolonged bear exposure,
(2) QQQ volatility scaling with explicit financing to compensate for reduced
exposure without uncontrolled leverage, and (3) simple QQQ/GLD/IEF momentum
rotation across existing broad exposures. Trend fails if reduced drawdown merely
buys persistently lower CAGR or is isolated to one crisis. Volatility scaling
fails if financing, turnover, timing delay, or an exposure-matched QQQ control
explains its apparent advantage. Rotation fails if diversification lowers return
below QQQ, or small parameter changes reverse the result. Fixed defaults and a
small neighborhood are preferable to another wide grid. The dot-com QQQ stress
should be reported separately from the common three-ETF period.

The protocol and main report own acceptance rules and final numerical outcomes;
this document records the data evidence available before those comparisons.
