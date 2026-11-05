# Risk parity as a replacement for the trend sleeve

Run 2026-09-29. Sleeve: `sleeves/risk_parity.py`. Experiment config:
`config/experiments/risk_parity.yaml` (the live book with risk parity in place of
`position_trend`). The live `config/settings.yaml` is unchanged.

**Rule** ([Asness, Frazzini & Pedersen 2012](https://www.aqr.com/Insights/Research/Journal-Article/Leverage-Aversion-and-Risk-Parity)):
- Hold SPY, EFA, EEM, TLT, IEF, GLD and DBC, each weighted by 1 / its volatility over 3 years
  (756 days, the paper's window).
- Fully invested and rebalanced monthly.
- The paper then levers the whole portfolio to 10% volatility. A $5k account with the book's
  1.0 gross cap can't, so this version is unlevered.

## Results (2008-2026, $5k, IBKR Tiered, 5 bps)
| | CAGR | Sharpe | Max DD | Trades/yr | Commissions | Corr. with momentum |
|---|---|---|---|---|---|---|
| position_trend (current) | 5.0% | 0.73 | -14.4% | 27 | $194 | 0.85 |
| **position_riskparity** | 5.8% | 0.74 | -18.0% | 8 | $54 | **0.59** |
| combined book with trend | 6.4% | 0.82 | -11.5% | 76 | $532 | |
| **combined book with risk parity** | 6.6% | 0.87 | -11.3% | 66 | $462 | |

- **Robustness grid** (vol window 63/252/756): Sharpe 0.65-0.74.
  - Before/after 2017: 0.53/0.78, 0.48/0.81, 0.56/0.91. Positive in both halves at every
    setting.
  - Walk-forward re-tuning: 0.66, vs 0.67 for fixed params.
  - The paper's 756-day window happens to be the best of the three. It was chosen before
    running, but read the 0.74 as the top of a 0.65-0.74 range.
- **It starts in 2011:** the 3-year window leaves it in cash for 2008-2010, which understates
  its CAGR over the full period.
- **2022** (gross, no costs): risk parity -12.0%, trend -5.6%, SPY -18.2%. Its known weakness
  is stocks and bonds falling together, when there's no trend filter to step aside. 2025 was
  its best year (+22%, gold).

## Verdict
It's a reasonable swap, not a clear win. At the same Sharpe it is much less correlated with
momentum (0.59 vs 0.85), which is what the pending decision in CLAUDE.md needed. It lifts the
combined book from 0.82 to 0.87 and cuts trading costs. The price is a worse 2022 and a deeper
standalone drawdown.

Changing `config/settings.yaml` is the owner's call. Nothing was switched.
