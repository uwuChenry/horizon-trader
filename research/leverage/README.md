# How much leverage on semiconductors is too much? SMH vs SOXL vs SMH on margin

Run 2026-09-27 with `uv run python -m horizon_trader.backtest.leverage`. Code:
`src/horizon_trader/backtest/leverage.py`. $5k at IBKR Pro, dividend-adjusted daily prices,
margin interest at IBKR Pro's rate for loans up to $100k: Fed funds + 1.5%, which is 5.38% today
([IBKR margin rates](https://www.interactivebrokers.com/en/trading/margin-rates.php); Fed funds
from [FRED DFF](https://fred.stlouisfed.org/series/DFF)).

## Answer first

- **The right amount of leverage depends on which history you believe, and the range is
  huge.** The growth-optimal (Kelly) leverage on SMH was **1.05x** measured from June 2000,
  which includes the dot-com crash. It was **2.9x** measured from 2010, a 16-year semis boom,
  and **2.4x** over the last 5 years. You can't know which kind of decade comes next.
- **Too much leverage costs more than too little.** Past about 2x Kelly, extra leverage *lowers*
  the long-run return while raising the risk. From 2000, 2x SMH made 5% a year against 10.9%
  for 1x, 3x lost 12% a year, and SOXL turned $5k into **$108**.
- **In every 5-year window since 2000** (256 windows, one starting each month):

| strategy | median CAGR | 10th percentile | windows that fell 80%+ at some point |
|---|---|---|---|
| SMH 1x | 17.1% | −5.6% | 1.6% |
| SMH 1.5x | 22.9% | −14.1% | 26% |
| SMH 2x (Reg T max) | 27.1% | −24.7% | 32% |
| SMH 3x | 26.0% | −48.3% | 59% |
| SOXL (synthetic before 2010) | 15.9% | −43.5% | 70% |

  Going from 1x to 1.5x adds about 6 points of median return, but the chance of an 80%
  drawdown jumps from 2% to 26%. Above 2x the median stops improving and only the risk grows.
- **SOXL is worse than 3x SMH.** It tracks a different index (ICE Semiconductor) and pays
  about 1% in fees plus swap financing. Since 2010: SOXL 39.9% a year vs 48.2% for SMH at a
  constant 3x. Both fell about 90% at the worst point.
- **Verdict:** for a semis-only position, **more than about 1.5x is too much**, and even 1.5x
  means accepting a 1-in-4 chance of an 80% drawdown in any 5-year stretch. 2x is IBKR's Reg T
  ceiling. It paid off hugely in 2010–2026 and was nearly wiped out in 2000–2002. 3x and SOXL
  only work if the next crash is milder than 2000 or 2008.

## Rules (fixed before running)

- **Constant leverage:** SMH at a fixed 0–5x, rebalanced daily, with interest charged on the
  borrowed part. Above 2x this needs portfolio margin ($110k+), so it maps the trade-off rather
  than an account you can open at $5k.
- **Margin account:** a real Reg T account. It borrows up to 2x, then rebalances to target on
  the first trading day of each month, or never. Below 25% equity (SMH maintenance) at a close,
  IBKR force-sells back to 2x. The model charges 5 bps plus 50 bps of extra slippage on those
  sales. Real liquidations happen intraday and can be worse.
- **SOXL:** the real fund from 2010, bought and held. Before that, a synthetic version: 3x
  SOXX daily, minus 0.95% in fees and 2 × (Fed funds + 0.5%) for swap financing; 3x SMH before
  SOXX existed (2001-07). Where both exist, the synthetic tracks the real SOXL closely: 0.997
  daily correlation, 40.4% vs 39.8% a year. SOXL/SMH mixes and SOXL plus cash are rebalanced
  monthly with no margin.
- Uninvested cash earns 0 (IBKR pays no interest on the first $10k). Dividend withholding is
  ignored.

## Results

### From June 2000 (SMH's first day, near the dot-com top) to Sep 2026

| strategy | CAGR | Sharpe | max DD | worst year | $5k becomes | margin calls |
|---|---|---|---|---|---|---|
| SMH 1x | 10.9% | 0.47 | −86% | −48% | $75,487 | |
| SMH 1.5x daily | 9.6% | 0.44 | −98% | −67% | $55,279 | |
| SMH 2x daily | 5.0% | 0.42 | −99.7% | −81% | $18,066 | |
| SMH 3x daily | −12.2% | 0.40 | −100% | −95% | $165 | |
| SMH 1.5x margin, monthly | 9.7% | 0.44 | −98% | −68% | $57,275 | 0 |
| SMH 1.5x margin, never rebalanced | 0.6% | 0.30 | −99.6% | −79% | $5,860 | 4 |
| SMH 2x margin, monthly | 4.4% | 0.42 | −99.8% | −83% | $15,696 | 0 |
| SMH 2x margin, never rebalanced | −2.2% | 0.26 | −99.8% | −86% | $2,781 | 5 |
| SOXL (synthetic), buy and hold | −13.6% | 0.40 | −100% | −96% | $108 | |
| SOXL 25% + SMH 75% (~1.5x) | 9.0% | 0.43 | −97% | −67% | $48,604 | |

### From March 2010 (SOXL's first day)

| strategy | CAGR | Sharpe | max DD | $5k becomes | interest paid |
|---|---|---|---|---|---|
| SMH 1x | 27.1% | 0.96 | −45% | $264k | |
| SMH 1.5x margin, monthly | 37.5% | 0.94 | −62% | $968k | $41k |
| SMH 2x margin, monthly | 46.0% | 0.93 | −75% | $2.6M | $178k |
| SMH 3x daily | 48.2% | 0.89 | −90% | $3.4M | |
| SOXL, buy and hold | 39.9% | 0.83 | −90.5% | $1.3M | |
| SOXL 25% + SMH 75% (~1.5x) | 34.4% | 0.89 | −62% | $662k | |

### Last 5 years

SMH 1x: 35.8%, −45% max DD. SMH 2x on margin, monthly: 55.4%, −75%. SOXL: 26.8%, −90.5%. The
2022 drawdown alone took SOXL down 90%. The same 2x margin account left unrebalanced hit a
margin call in 2022 and made only 32.1%.

### CAGR by constant leverage on SMH

| leverage | from 2000-06 | from 2010-03 | last 5 years |
|---|---|---|---|
| 1x | 10.9% | 27.1% | 35.8% |
| 1.5x | 9.6% | 36.6% | 46.5% |
| 2x | 5.0% | 43.6% | 52.7% |
| 2.5x | −2.4% | 47.6% | 53.9% |
| 3x | −12.2% | 48.2% | 49.7% |
| 4x | −35.4% | 39.4% | 27.4% |
| Kelly estimate | 1.05x | 2.91x | 2.36x |

## Things the numbers don't show

- **Monthly rebalancing avoided every margin call; "set and forget" got liquidated 3–5 times
  from 2000.** When the price falls, an unrebalanced loan pushes leverage up
  (2x → 3x → 4x) until IBKR sells at the bottom. Monthly rebalancing sells on the way down
  instead. Choosing leverage means choosing rebalancing too.
- **The sample choice is the whole answer.** The 2010–2026 rows are what semis did in their
  best 16 years ever. The Sharpe ratio barely moves with leverage (0.96 → 0.89 from 1x to 3x),
  so leverage adds no skill, just the same bet at a bigger size.
- **This concentrates further on one sector.** The owner's long-term account is already
  concentrated in AI hardware. Leverage on top of that stacks the same risk.
- Not modelled: intraday liquidation prices, IBKR house margin above 25% on SMH during volatile
  periods, taxes, dividend withholding, and options or LEAPS as a way to get defined-risk
  leverage.
