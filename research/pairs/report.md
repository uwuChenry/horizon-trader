# Competitor pairs backtest

Frozen rules, named competitors, next-open fills. Sample: 2017-01-03 to 2026-10-09.
**The base strategy fails the requirement of positive net returns in both
2024–2025 and 2026 YTD.** This is one specified strategy, not a test of every possible pairs model.

## Rules

KO/PEP, HD/LOW, MCD/YUM. Compute log relative total-return prices against the previous
60 closes, excluding today's observation. Enter at 2–4 standard deviations, long the
relatively cheap leg and short the rich leg. Freeze the entry mean/std. Exit after
crossing that mean, reaching 4 original standard deviations, or holding 40 sessions.
Every signal fills next open. Each pair has one third of account equity in gross
exposure, half per leg. Quantities are determined at the signal close, rounded down
to whole shares, and held constant. Reject dollar imbalance above 15% and entries
that exceed 1x gross at execution. Idle allocations stay in cash.

Base: $5,000, IBKR Tiered, 5 bps per fill, 1% annual short borrow (calendar/360),
30% withholding on long dividends, full short dividend liability. Cash earns zero.
Longs are funded from equity; short proceeds do not fund longs. Exceptional debit
balances cost an assumed 8% annually: **$0.00 charged** in the base run.
Whole-share sizing and skip rules apply to the cost-free comparison too.

## Results

| variant | period | return | cagr | sharpe_zero_rf | max_dd | trades | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Base net | Full 2017-2026 | -3.74% | -0.39% | -0.11 | -9.60% | 196 | +42.86% |
| Base net | 2017-2023 | +3.90% | +0.55% | 0.19 | -5.79% | 144 | +43.75% |
| Base net | 2024-2025 | -3.16% | -1.59% | -0.61 | -6.58% | 31 | +38.71% |
| Base net | 2026 YTD | -4.53% | -5.83% | -2.39 | -5.44% | 10 | +30.00% |
| Before all costs | Full 2017-2026 | +26.96% | +2.47% | 0.74 | -5.63% | 203 | +44.83% |
| Before all costs | 2017-2023 | +30.18% | +3.84% | 1.10 | -4.94% | 152 | +46.05% |
| Before all costs | 2024-2025 | -0.48% | -0.24% | -0.08 | -4.88% | 34 | +38.24% |
| Before all costs | 2026 YTD | -3.71% | -4.78% | -1.96 | -4.73% | 10 | +30.00% |

Sharpe uses a zero risk-free rate and all trading sessions, including flat days.
The 2026 return is YTD; its CAGR column mechanically annualizes a partial year.
Each subperiod restarts flat at $5,000 with earlier observations used for warm-up.
Consequently these subperiod returns need not chain into the continuous full run.
Full-period ending equity: **$4,813.16**.

## Pair contributions to the uninterrupted base portfolio

| symbol | closed_trades | closed_pnl | gross_pnl | costs | win_rate | open_pnl | total_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- |
| KO/PEP | 77 | $-392.98 | $-50.25 | $342.73 | +36.36% | $-21.59 | $-414.58 |
| HD/LOW | 63 | $219.33 | $472.81 | $253.48 | +46.03% | $0.00 | $219.33 |
| MCD/YUM | 56 | $24.85 | $249.30 | $224.45 | +48.21% | $-16.44 | $8.41 |

Pair P&L includes any final open mark. Win rates are for closed round trips only.
Full-period modeled costs: commission $300.71, slippage $309.08, borrow $115.69, withholding $98.61, financing $0.00.
Gross and net paths size independently as equity changes, so their NAV difference
is not simply the sum of net-run costs. Average gross exposure was
45.8%; maximum was 101.2%.
Holding the net run's exact quantities and dates fixed, adding back modeled costs
produces ending equity of **$5,637.25**. Direct cost drag is
$824.09; the remaining difference from the independent
cost-free run comes from sizing and which entries were accepted. Lower costs need
not monotonically improve a rounded-share path when the trades themselves change.

## Predeclared sensitivity checks

Values below are cumulative period returns, **not annualized**. Each row changes
one assumption except the explicitly cost-free and expanded-universe diagnostics.
The baseline was not replaced by the best-looking row.

| variant | 2017-2023 | 2024-2025 | 2026 YTD | Full 2017-2026 |
| --- | --- | --- | --- | --- |
| Base net | +3.90% | -3.16% | -4.53% | -3.74% |
| Before all costs | +30.18% | -0.48% | -3.71% | +26.96% |
| 1 bp fills | +13.38% | -2.81% | -4.27% | +4.58% |
| 10 bp fills | +0.89% | -3.59% | -4.66% | -7.49% |
| 0.25% borrow | +1.57% | -2.89% | -4.46% | -5.22% |
| 3% borrow | +1.20% | -3.37% | -4.72% | -7.33% |
| 10% borrow | -10.61% | -6.23% | -5.16% | -18.43% |
| Fixed commissions | +1.11% | -4.27% | -4.89% | -9.09% |
| $100k capital | +16.92% | -1.06% | -4.10% | +8.02% |
| Fractional diagnostic | +15.95% | -3.17% | -4.30% | +5.93% |
| 40-day lookback | -1.98% | -6.06% | -0.65% | -10.89% |
| 90-day lookback | +8.44% | -6.17% | -3.69% | -4.78% |
| 1.5 z entry | +18.59% | -4.71% | -5.59% | +7.70% |
| 2.5 z entry | +1.28% | +0.17% | -2.50% | -2.56% |
| 20-session cap | -4.82% | -3.37% | -4.31% | -12.27% |
| 60-session cap | +16.01% | -0.94% | -5.46% | +7.30% |
| Correlation >= 0.6 | +12.28% | -4.23% | -2.95% | +1.85% |
| Expanded five pairs | +0.77% | -5.76% | -0.84% | -7.11% |
| KO/PEP alone | -17.95% | -8.58% | -8.78% | -31.63% |
| HD/LOW alone | +25.41% | -1.51% | -1.80% | +19.27% |
| MCD/YUM alone | +25.84% | +5.93% | -1.56% | +31.33% |

The single-pair rows allocate the whole account's 1x gross limit to that pair;
they therefore differ from its one-third allocation in the contribution table.
The $100k row also assumes zero cash/short-collateral interest, understating the
cash yield potentially available at that account size.

## Year-by-year, uninterrupted portfolio

| year | net | before_costs |
| --- | --- | --- |
| 2017 | -1.49% | +0.80% |
| 2018 | +4.76% | +7.22% |
| 2019 | -1.43% | +1.59% |
| 2020 | -2.42% | +7.84% |
| 2021 | +3.62% | +4.17% |
| 2022 | +2.39% | +5.25% |
| 2023 | -1.34% | +0.29% |
| 2024 | +0.90% | +2.35% |
| 2025 | -2.75% | -0.45% |
| 2026 | -5.58% | -4.29% |

## Uncertainty and limitations

A circular 20-session block bootstrap (2,000 draws, fixed seed) gives a 95%
interval of **-2.23% to +1.44%** for the base strategy's annualized mean
daily return. This is not a prediction interval or an independent validation;
few pairs, serial dependence, regime changes and retrospective selection remain.

Surviving pairs selected retrospectively; later periods are not pristine out-of-sample. Borrow availability/recalls unverified; 1% annual borrow and 5 bps fills assumed. 30% long dividend withholding; full short dividend liability; ex-date accrual. Constant commission schedule; cash and short collateral yield zero. Stops trigger at close and execute next open; prices can gap beyond the threshold. Open positions marked at last close, without hypothetical terminal liquidation costs.
The 2024+ dashboard split is chronological only. No valuation-multiple, earnings,
cointegration, or sector-neutrality claim is made. Similar products do not guarantee
economic convergence. Liquidity, exact auction execution, locate availability,
payment-date dividend timing and historical broker house margin were not reconstructed.
Recorded dividends and splits are handled explicitly; data come from a prototype
vendor rather than an audited point-in-time institutional feed.

## Long-only context

| benchmark | CAGR | Sharpe | max DD |
| --- | --- | --- | --- |
| SPY | +15.40% | 0.88 | -33.72% |
| Six stocks buy and hold | +10.24% | 0.63 | -37.99% |

These benchmarks use fractional total-return buy-and-hold before costs and taxes;
the six stocks are equally weighted at inception, not rebalanced daily. They carry
market exposure and have much higher invested capital than the pairs strategy.

## Artifacts and reproduction

- [Protocol](protocol.md), [settings](settings.json), [summary CSV](summary.csv),
  [verification](verification.json), [pair trades](net_trades.csv).
- Standalone interactive chart: `data/pairs_2026_10_12/pairs_report.html`.
- Daily ledger, exact leg fills and holdings: `data/pairs_2026_10_12/`.
- Dashboard bundles: `data\results\20261013-002313_competitor-pairs-net-5k-full-2017-2026`, `data\results\20261013-002313_competitor-pairs-net-5k-2026-ytd`.
- Run `.venv\Scripts\python.exe research/pairs_2026_10_12/run.py` against the
  frozen raw files; hashes are recorded in verification.json.
- Tests: `.venv\Scripts\python.exe -m pytest tests/test_pairs.py -q`.

Sources and motivation: [Gatev et al.](https://doi.org/10.1093/rfs/hhj020),
[Villota 2025](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5141328),
[IBKR commissions](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php),
[short-sale costs](https://www.interactivebrokers.com/en/pricing/short-sale-cost.php).
