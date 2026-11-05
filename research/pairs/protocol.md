# Competitor pairs: protocol fixed before performance was computed

Date: 2026-10-12. This is a retrospective research test, not live trading.

## Hypothesis and universe

Temporary deviations in the relative total-return prices of established competitors
subsequently reverse. This tests price mean reversion, not accounting valuation.
Primary pairs: KO/PEP, HD/LOW, MCD/YUM. An expansion check adds V/MA and XOM/CVX.
These are named, surviving firms selected today: do not generalize to an unbiased
historical universe or call the later sample a pristine prospective holdout.

## Fixed rules

- Use daily total-return adjusted closes for signals. Spread = log(A / B).
- At close t, compare the spread with its previous 60 sessions (excluding t).
  Enter if 2 <= abs(z) < 4. Long the relatively cheap stock, short the rich stock.
- Execute both legs at the next session's open. Freeze the signal mean and standard
  deviation at entry. Exit at the next open after the spread crosses that original
  mean, exceeds 4 original standard deviations, or has been held for 40 sessions.
  These are close-triggered exits, not guaranteed intraday stops. No averaging down.
- One position per pair. Each pair receives at most 1/N of account equity in gross
  exposure, split equally between legs; unused allocations stay in cash. Gross
  target across all pairs is 1x. Fixed shares between entry and exit.
- Whole shares, rounded down. Reject an entry if either leg is zero or the dollar
  imbalance exceeds 15% of the average leg value. Account capital = $5,000.
- Size with information available at the signal close; next-open gaps cannot
  increase planned share quantities. Recheck gross capacity at execution.
- No new position below $2,000 equity. Emergency exit on the next open if marked
  gross exposure exceeds 1.5x equity. No assumption of a guaranteed stop fill.

## Data, costs and periods

Freeze Yahoo daily OHLC, adjusted close, dividends and split actions separately from
existing caches, plus SHA256 hashes. Exclude the current incomplete session.
Use split-unadjusted historical execution prices and explicit dividend cash flows.
Start trading 2017-01-03, with 2016 warm-up; this avoids YUM's 2016 China spin-off
inside the trading period. End at the last complete common session, no later than
2026-10-09. Fail on missing required bars instead of filling across gaps.

Base costs: existing IBKR Tiered commission/fee model; assumed 5 bps adverse
slippage on every leg of entry and exit; assumed 1% annual stock-borrow fee,
actual calendar days / 360. Long dividend withholding = 30%; full short dividend
liability. Dividends are accrued on ex-date (payment-date cash timing is not modeled).
Cash and short collateral earn zero. At 1x gross, the long leg is funded from
account equity; short-sale proceeds are not treated as spendable financing.
Borrow availability/recalls and historical borrow quotes are unavailable. Fee rates
are a constant research approximation, not historical invoices.

Report full sample, 2017-2023, 2024-2025, and 2026 YTD. Restart each subperiod at
$5,000 with preperiod signal history and no inherited positions. Also report annual
returns of the uninterrupted run. SPY and equal-weight buy-and-hold of the six
primary stocks are contextual, long-only total-return references, not risk-matched.

## Predeclared comparisons (no winner selection)

- Zero execution costs, zero borrow, zero withholding; same whole-share rules.
- Base net; 1 bp and 10 bps fills; 0.25%, 3%, 10% borrow; Fixed commissions.
- $100,000 capital (zero cash yield remains a conservative simplifying assumption).
- Fractional shares as a sizing diagnostic, not an executable short-sale proposal.
- Lookbacks 40/60/90, entries 1.5/2/2.5, holding caps 20/40/60: change one
  parameter at a time, no optimization. The original rule remains the headline.
- Correlation filter: enter only if previous 60 daily return correlation >= 0.6.
- Expanded five-pair basket; each original pair alone. These are diagnostics.

Evidence threshold: base net positive in both recent subperiods, no single pair
carrying the result, and broadly positive neighboring settings. Report failures.
Use a 20-session block bootstrap of daily P&L returns for uncertainty; this does
not repair pair-selection bias or establish a causal arbitrage relationship.

## Verification

Tests for future-data truncation, next-open execution, frozen reference levels,
dividend entitlement and short liability, weekend borrow, split accounting, whole
share sizing, and cash/equity/trade reconciliation. Save daily ledger, fills,
pair round trips, cost breakdowns, sensitivity tables, and a standalone chart.

Sources: [Gatev et al.](https://doi.org/10.1093/rfs/hhj020),
[Villota 2025](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5141328),
[IBKR commissions](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php),
[IBKR short-sale costs](https://www.interactivebrokers.com/en/pricing/short-sale-cost.php).
The rules above are an original simple specification, not an exact paper replication.
