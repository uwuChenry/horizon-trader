# The daily ETF book: four sleeves, 2008 to today

**Verdict: the core of the system.** At $5k on IBKR Tiered pricing, the combined book makes
6.5% CAGR with a 0.83 Sharpe and a -12% max drawdown, against SPY's 11.3%, 0.64 and -52%.
Lower return, much smaller drawdowns. Momentum and vol-managed SPY carry it; the trend sleeve
is largely redundant and RSI(2) mean reversion is weak.

Reproduce with `uv run python -m horizon_trader.backtest.run [--plan fixed] [--save]` and the
parameter grids with `uv run python -m horizon_trader.backtest.robustness`.

## Results (2008 to 2026, $5k, IBKR Tiered)

| Sleeve | CAGR | Sharpe | Max DD | Verdict |
|---|---|---|---|---|
| Combined book (0.3/0.25/0.2/0.15) | 6.5% | 0.83 | -12% | Fixed pricing: 5.8%, 0.75. Tiered cuts 18-year commissions from $1,435 to $532 |
| position_momentum (ETF 12-1 rotation) | 9.9% | 0.76 | -18% | Core. Only the 12-month lookback is robust; 6-month/top-2 blew up to a -45% drawdown |
| position_volmanaged (SPY, Moreira-Muir) | 9.7% | 0.81 | -21% | Most robust (Sharpe 0.66-0.80 across the grid, 1.00 out-of-sample from 2013). 0.81 correlated with SPY |
| position_trend (TSMOM, inverse-vol) | 5.0% | 0.73 | -14% | Stable but 0.85 correlated with momentum, so largely redundant |
| swing_meanrev (RSI(2)) | 2.7% | 0.49 | -19% | Weak at every setting and costly. Lowest correlation to the others |
| MACD 12/26/9 (SPY/QQQ/IWM) | 4.8% | 0.44 | -26% | Below buy-and-hold even with zero costs. Not in config |
| SPY buy & hold | 11.3% | 0.64 | -52% | Benchmark |

## Caveats

- Signals from the close of day t trade at the open of day t+1; targets are re-applied daily
  with a 2% rebalance band.
- yfinance prices: no delisted tickers. Dividend-adjusted prices ignore the 30% US withholding
  on dividends for non-US holders (about -0.4%/yr on SPY).
- At $5k, whole shares misweight 11% of the book today (SPY 22.5% -> 15.3%, QQQ and GLD -> 0).
  IBKR paper needs `share_decimals: 0` (`config/experiments/whole_shares.yaml`).
- [Risk parity](../risk_parity/README.md) is a tested replacement for the trend sleeve.

## Forward test

Shadow mode since 2026-10-01 (signal date 2026-09-30): `uv run python -m
horizon_trader.run_daily --mode shadow` every trading day after 16:10 ET or pre-market. The
ledger lives in `data/live/daily_book_shadow/` and shows up in the dashboard's live page.
