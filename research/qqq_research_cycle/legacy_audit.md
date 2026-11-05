# Existing daily simulator audit — 2026-10-01

The four configured daily sleeves and combined book reproduce the repository's
published results to rounding and the additional September 2026 observations.
The combined book reduces drawdown substantially but returns far less than QQQ.
No existing configured sleeve meets the requested return-and-drawdown objective.

## Local baseline reproduction

From the repository root, using the existing environment:

```powershell
.venv\Scripts\python.exe research/qqq_research_cycle/reproduce_legacy.py
```

The script reads `data/bars/*.parquet` directly, never calls the normal daily
refresh pipeline, uses all pre-2008 observations to warm indicators, and fixes
the final observation at 2026-09-30. It saves source SHA-256 hashes and absolute
paths, a settings snapshot, equity curves, exact metrics, and reconstructed
cash diagnostics under `results/legacy*`. To use the saved settings:

```powershell
.venv\Scripts\python.exe research/qqq_research_cycle/reproduce_legacy.py --config research/qqq_research_cycle/results/legacy_config.json
```

The JSON settings snapshot is also valid YAML for the existing settings loader.
The cache files are local licensed/provider data and are not copied into Git.
Reproduction requires the recorded cache files; matching hashes establish the
same inputs. No data credentials, broker connection, orders, or live settings
changes are required.

Evaluation dates are 2008-01-02 through 2026-09-30, $5,000 initial cash, configured
IBKR Tiered fees and 5 basis points adverse price movement per fill, 2% rebalance
band, $25 minimum trade, and four-decimal synthetic shares. The first equity
observation is cash. Each strategy, including both buy-and-hold controls, first
becomes eligible to trade at the next session's open. Dividends are represented
by the provider's adjusted OHLC series. Sharpe uses daily arithmetic returns,
sample standard deviation, 252 sessions/year and zero risk-free rate. CAGR uses
actual calendar elapsed years. Equity is marked at daily close; drawdown is
therefore a close-to-close measure, not an intraday liquidation bound.

| Strategy | Net CAGR | Sharpe | Maximum drawdown | Mean net exposure |
|---|---:|---:|---:|---:|
| Combined | 6.4% | 0.82 | -11.5% | 62.9% |
| ETF momentum rotation | 9.8% | 0.76 | -17.7% | 91.1% |
| Trend | 5.0% | 0.72 | -14.4% | 69.2% |
| Volatility managed SPY | 9.6% | 0.80 | -20.6% | 81.2% |
| Swing mean reversion | 2.7% | 0.48 | -19.3% | 12.7% |
| SPY buy-and-hold | 11.3% | 0.64 | -51.9% | 100.0% |
| QQQ buy-and-hold | 16.4% | 0.79 | -49.4% | 100.0% |

## Material defects fixed

1. `backtest/sim.py` previously filled missing opens using the previous close.
   That invented executable liquidity and could allow exiting a halted or
   missing symbol at a stale price. Missing, nonpositive, and infinite opens
   now prevent that symbol from trading. Held positions remain held until a
   valid open returns. Their prior close is used only for opening valuation;
   today's future close cannot influence sizing of other assets. Tests cover
   opening orders, deferred exits, and sizing another symbol while one is
   unavailable. No post-2008 opens are missing in the ten-ETF baseline, so this
   fix leaves its results unchanged.
2. `backtest/analytics.py` calculated Sortino using the conditional standard
   deviation of negative returns. This discards the frequency of losses and
   demeans their magnitude; repeated equal losses incorrectly have zero risk.
   Sortino now uses the square root of the mean squared shortfall below zero
   across all daily observations, with a zero minimum acceptable return. A
   regression test checks repeated equal losses mixed with gains. Previously
   saved dashboard Sortino values use the old convention and need regeneration.

The shared daily order path is retained. No existing user-modified file was
edited for either fix.

## Remaining research limitations

- **Free borrowing:** `PaperBroker` does not enforce cash affordability or
  charge debit interest. The standalone momentum sleeve has negative cash in
  44.4% of sessions, mean debit balance 0.441% of equity and maximum 3.35%; trend
  has maximum 6.91%. The combined book never borrows in this reproduction.
  Buy-and-hold borrows a few dollars to cover initial costs. This is a small
  distortion here, but the engine is inappropriate for leveraged research
  without explicit financing. A missing quote can also prevent a desired sale
  while another name is bought; freezing the unavailable holding does not add
  a new cash/gross limit.
- **Cash yield:** all uninvested cash earns zero. That assumption may be
  appropriate for an uncompensated small broker cash balance but is different
  from investing idle cash in a tradeable Treasury fund. Such a fund requires
  its own fills, share rounding and costs. It must not receive a frictionless
  historical rate by assumption.
- **Adjusted share accounting:** yfinance `auto_adjust=True` correctly provides
  a useful total-return proxy, but adjusted units are not actual historical
  share counts. Applying per-share fees, fractional rounding, and minimum
  trade thresholds to them does not exactly model raw-price executions,
  distributions and splits. Current tax withholding is not modeled. Treat
  this as a tax-neutral total-return comparison; owner-specific after-tax
  feasibility remains untested.
- **Opening order sizes:** targets use yesterday's close, but share quantities
  are computed from today's exact opening price and opening account NAV. A
  market-on-open order submitted earlier cannot know those prices. Accurate
  execution research must use precommitted share quantities or a stated delay
  after observing the open. Commission schedules are held fixed across history
  and are scenario assumptions, not reconstructed historical invoices.
- **Unvalidated brokerage granularity:** the settings use fractional shares;
  existing repository documentation reports IBKR API rejection of fractional
  orders. Whole-share execution matters for a $5,000 account. Fee plan and
  exchange-fee assumptions require confirmation from the chosen account's
  actual paper fills; no account settings were changed.
- **Stale valuations and survivorship:** forward-filled closes retain a
  position's stale marked value. They do not resolve missing observations,
  delistings, or cash settlement. The ten baseline ETFs have complete
  post-2008 open/close panels, but that does not make the same simulator valid
  for a changing stock universe. Adjusted cache histories are revised by the
  vendor; hashes record the version used.
- **Metrics conventions:** reported legacy turnover is total absolute traded
  dollars divided by mean equity and elapsed years, including opening trades;
  it is a two-sided dollar measure, not per-session normalized turnover.
  `commission` in the fill table includes modeled pass-through fees as well
  as commission. Sharpe is not excess to a cash hurdle. First-day return is
  included for these simulator curves because the initial observation is
  starting cash; imported curves lacking that observation can omit it.
- **No untouched history:** the repository has repeatedly studied the same
  available ETF history, including its later periods. New chronological
  splits can limit this cycle's selection but cannot restore an untouched
  historical holdout. Generic sleeve truncation tests already verify that
  cutting off future data preserves current target weights.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest tests/test_backtest.py tests/test_analytics.py tests/test_sleeves.py tests/test_portfolio.py tests/test_rebalance.py -q -p no:cacheprovider --basetemp=data/tmp/pytest_sim_audit_20261001
.venv\Scripts\ruff.exe check src/horizon_trader/backtest/sim.py src/horizon_trader/backtest/analytics.py tests/test_backtest.py tests/test_analytics.py research/qqq_research_cycle/reproduce_legacy.py
```

62 tests passed; lint passed. The first test invocation used pytest's existing
user-wide temporary directory and failed only during one cache fixture's setup
because that directory was inaccessible. An isolated workspace temporary
directory allowed the complete selected suite to run. Choose a fresh temporary
directory name on systems retaining pytest output from another security context.
