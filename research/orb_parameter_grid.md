# ORB parameter grid: does optimizing the parameters help?

Run 2026-09-25 with `uv run python -m horizon_trader.intraday.orb_grid`. Code:
`src/horizon_trader/intraday/orb_grid.py`. Raw results (3,840 rows):
`data/results/orb_grid.parquet`. Follows [ORB experiments](orb_experiments.md).

## Answer first

**No. Optimizing on past data made the out-of-sample results worse, in every scenario.**

- In each of the 8 slippage × account combinations, the configuration with the best
  2021–23 Sharpe did **worse in 2024–26 than the untouched baseline**. Only 6–14% of the 480
  configurations beat the baseline out of sample.
- After correcting for 480 tries, **no configuration's Sharpe is statistically distinguishable
  from luck** (deflated Sharpe probability 0.00–0.48; ≥0.95 would be convincing).
- What *is* robust is the structure, which holds in both periods and every scenario:
  **hold to the close** (profit targets always hurt), **stop around 1 ATR** (tight stops
  fail), and **higher relative volume helps a little**.
- **Slippage matters more than any parameter.** The baseline's out-of-sample Sharpe goes from
  1.05 (0¢) to 0.94 (1¢), 0.82 (measured, stop-limit entry) and 0.53 (measured, stop-market
  entry).

## What was tested

Signal: the paper's selection, top-1 stock by relative volume, direction from the first
5-minute candle, entry on a break of its high/low. $5k and $20k, 1% risk per trade, IBKR Pro
Tiered. Every combination of:

| Parameter | Values |
|---|---|
| Stop loss | 0.25 / 0.5 / 0.75 / **1** / 1.5 / 2 ATR from the fill |
| Profit target (reward:risk) | **hold to the close** / 1R / 2R / 3R / 5R |
| Relative-volume filter | **any** / ≥ 5 / ≥ 8 / ≥ 12 |
| Latest entry time | **any** / 10:00 / 10:30 / 11:00 |
| Slippage scenario | 0¢ (paper) / 1¢ / measured stop-market / measured stop-limit |
| Account | $5k / $20k |

Baseline values in bold. 480 configurations × 4 scenarios × 2 accounts = 3,840 runs, each
evaluated on train, test and the full period (45 seconds on 22 cores).

**Slippage scenarios, and why:**

| Scenario | Entry | Stop-out | Grounding |
|---|---|---|---|
| 0¢ (paper) | stop-market, 0¢ | 0¢ | What the paper and most backtests assume |
| 1¢ | stop-market, 1¢ | 1¢ | Best case: very liquid large caps often trade with a 1¢ spread (the minimum tick), so crossing it costs about 1¢ at most |
| measured, stop-market | stop-market, 4.5¢ | 4¢ | Measured on these exact trades from 1-second bars |
| measured, stop-limit | limit at the trigger (fills at the limit; can miss) | 4¢ | Our best realistic order type |

The measured ~4¢ (10–14 basis points on these stocks) sits inside the academic range:
Schwarz, Barber, Huang, Jorion & Odean (Journal of Finance, 2025) sent 85,000 identical
market orders through six retail accounts and found round-trip execution costs of **0.07%–0.46%**
excluding commissions. **IBKR Pro captured 19% of the spread as price improvement, the lowest
of the brokers tested** (TD Ameritrade 47%, Fidelity/E*Trade ~35%, Robinhood 27%). Breakout
entries are harder than their random-timing orders, so 0–1¢ is optimistic.

**Protocol (fixed before running):** train = Oct 2021 – Dec 2023, test = Jan 2024 – Sep 2026.
Pick the best config on train (≥100 train trades), judge it on test only. Also: rank
correlation of train vs test Sharpe across configs, the deflated Sharpe ratio (Bailey &
López de Prado 2014) for 480 trials, and ablations.

## Result 1: the config picked on train fails on test

| Scenario | Account | Best config, chosen on train | Train Sharpe | **Test Sharpe** | Baseline test Sharpe | Median config test Sharpe | Configs beating baseline on test |
|---|---|---|---|---|---|---|---|
| 0¢ (paper) | $5k | stop 0.75 ATR · target 5R · relvol ≥ 12 · any time | 1.51 | **0.55** | 1.05 | 0.58 | 6% |
| 0¢ (paper) | $20k | stop 0.75 ATR · target 5R · relvol ≥ 12 · any time | 1.54 | **0.60** | 1.11 | 0.73 | 8% |
| 1¢ | $5k | stop 0.75 ATR · target 5R · relvol ≥ 12 · any time | 1.34 | **0.39** | 0.94 | 0.43 | 6% |
| 1¢ | $20k | stop 0.75 ATR · target 5R · relvol ≥ 12 · any time | 1.38 | **0.44** | 0.99 | 0.58 | 8% |
| measured, stop-market | $5k | stop 0.75 ATR · target 5R · relvol ≥ 12 · any time | 0.80 | **−0.15** | 0.53 | −0.04 | 9% |
| measured, stop-market | $20k | stop 0.75 ATR · target 5R · relvol ≥ 12 · any time | 0.84 | **−0.09** | 0.60 | 0.09 | 14% |
| measured, stop-limit | $5k | stop 0.75 ATR · hold · relvol ≥ 12 · entries by 11:00 | 0.96 | **0.75** | 0.82 | 0.31 | 10% |
| measured, stop-limit | $20k | stop 0.75 ATR · hold · relvol ≥ 8 · entries by 11:00 | 0.99 | **0.55** | 0.89 | 0.41 | 13% |

The train-vs-test rank correlation is 0.25–0.70: the in-sample ranking does separate bad
configs (tight stops, 1R targets) from reasonable ones, but among the good ones it picks noise.
The winner keeps being "0.75 ATR stop + 5R target", which looked best in 2021–23 and was
among the worst in 2024–26.

## Result 2: after 480 tries, nothing is significant

The best full-period config in each scenario, against the Sharpe that the best of 480 random
tries would show by luck:

| Scenario | Account | Best full-period config | Sharpe | Best-of-480 by luck | Deflated Sharpe (prob.) |
|---|---|---|---|---|---|
| 0¢ (paper) | $5k | stop 1 ATR · hold · relvol ≥ 12 · entries by 10:00 | 1.18 | 1.21 | 0.47 |
| 0¢ (paper) | $20k | stop 1 ATR · hold · relvol ≥ 12 · any time | 1.22 | 1.23 | 0.48 |
| 1¢ | $5k | stop 1 ATR · hold · relvol ≥ 12 · entries by 10:00 | 1.07 | 1.62 | 0.08 |
| measured, stop-limit | $5k | stop 1 ATR · hold · relvol ≥ 12 · entries by 10:00 | 0.97 | 2.96 | 0.00 |
| measured, stop-limit | $20k | stop 1 ATR · hold · relvol ≥ 12 · entries by 10:00 | 1.01 | 2.77 | 0.00 |

Caveat: the 480 configs are highly correlated (they share most trades), so the effective
number of independent tries is smaller and this test is on the harsh side. It still says the
same thing as Result 1: the grid's best numbers are not evidence of a better strategy.

## Result 3: one change at a time from the baseline (measured, stop-limit, $5k)

| Change from baseline | Train Sharpe | Test Sharpe | Full Sharpe | Full CAGR | Max DD |
|---|---|---|---|---|---|
| **Baseline** (1 ATR · hold · any relvol · any time) | 0.50 | 0.82 | 0.70 | 12.0% | −21.7% |
| stop 0.25 ATR | −1.16 | 0.27 | −0.25 | −20.3% | −80.8% |
| stop 0.5 ATR | 0.21 | 0.57 | 0.44 | 9.6% | −47.6% |
| stop 0.75 ATR | 0.83 | 0.34 | 0.55 | 10.7% | −25.3% |
| stop 1.5 ATR | 0.56 | 0.68 | 0.65 | 8.2% | −16.2% |
| stop 2 ATR | 0.52 | 0.66 | 0.62 | 6.2% | −15.6% |
| target 1R | −0.53 | −0.19 | −0.37 | −4.8% | −31.9% |
| target 2R | 0.21 | 0.40 | 0.33 | 3.7% | −21.1% |
| target 3R | 0.38 | 0.50 | 0.46 | 6.0% | −20.5% |
| target 5R | 0.41 | 0.52 | 0.49 | 6.8% | −21.8% |
| relvol ≥ 5 | 0.51 | 0.82 | 0.71 | 12.1% | −21.6% |
| relvol ≥ 8 | 0.61 | 0.85 | 0.76 | 13.1% | −21.8% |
| relvol ≥ 12 | 0.61 | 1.01 | 0.86 | 15.0% | −21.7% |
| entries by 10:00 | 0.54 | 1.01 | 0.84 | 14.4% | −19.3% |
| entries by 10:30 | 0.52 | 1.01 | 0.82 | 14.2% | −19.7% |
| entries by 11:00 | 0.55 | 0.99 | 0.82 | 14.2% | −20.3% |

The same pattern holds at 1¢ slippage (see the script output). **Every profit target and
every stop tighter than 1 ATR made things worse. Relative volume and the entry cutoff were
the only changes that helped in both halves.**

## Result 4: stop × profit target (measured, stop-limit, $5k, no filters)

Test Sharpe (2024–26); train Sharpe in brackets:

| Stop | Hold | 1R | 2R | 3R | 5R |
|---|---|---|---|---|---|
| 0.25 ATR | 0.27 (−1.16) | −2.66 (−3.54) | −1.53 (−2.71) | −1.52 (−2.41) | −1.17 (−1.83) |
| 0.5 ATR | 0.57 (0.21) | −0.89 (−1.19) | −0.77 (−0.54) | −0.58 (−0.25) | −0.34 (0.36) |
| 0.75 ATR | 0.34 (0.83) | −1.15 (−0.58) | −0.61 (0.06) | −0.59 (0.69) | −0.21 (0.79) |
| **1 ATR** | **0.82 (0.50)** | −0.19 (−0.53) | 0.40 (0.21) | 0.50 (0.38) | 0.52 (0.41) |
| 1.5 ATR | 0.68 (0.56) | −0.22 (−0.39) | 0.14 (0.43) | 0.15 (0.49) | 0.52 (0.58) |
| 2 ATR | 0.66 (0.52) | 0.20 (0.03) | 0.30 (0.49) | 0.46 (0.51) | 0.60 (0.52) |

"Hold" is the best column at every stop width, in both periods. The 1–2 ATR rows form a
stable plateau; 0.75 ATR is the train-period peak that collapses out of sample.

## Result 5: the pre-registered ideas, combined

These are the two ideas that passed the earlier pre-registered test, now combined. Treat the
test column with care: this combination was chosen after seeing earlier results on the same
data.

| Config (measured, stop-limit) | Account | Train Sharpe | Test Sharpe | Full Sharpe | Full CAGR | Max DD | Trades/yr |
|---|---|---|---|---|---|---|---|
| Baseline: 1 ATR · hold · any relvol · any time | $5k | 0.50 | 0.82 | 0.70 | 12.0% | −21.7% | 199 |
| 1 ATR · hold · relvol ≥ 12 · any time | $5k | 0.61 | 1.01 | 0.86 | 15.0% | −21.7% | 176 |
| 1 ATR · hold · any relvol · entries by 10:30 | $5k | 0.52 | 1.01 | 0.82 | 14.2% | −19.7% | 180 |
| **1 ATR · hold · relvol ≥ 12 · entries by 10:30** | $5k | 0.59 | 1.16 | 0.94 | 16.4% | −19.7% | 160 |
| **1 ATR · hold · relvol ≥ 12 · entries by 10:30** | $20k | 0.67 | 1.20 | 0.99 | 17.6% | −19.7% | 160 |
| 1 ATR · hold · relvol ≥ 12 · entries by 10:30, at 1¢ | $5k | 0.79 | 1.24 | 1.06 | 19.0% | −19.2% | 165 |
| 1 ATR · hold · relvol ≥ 12 · entries by 10:30, at 0¢ | $5k | 0.91 | 1.34 | 1.18 | 21.5% | −18.2% | 165 |

All at 1% risk per trade; 2% roughly doubles CAGR and drawdown (see ORB experiments,
Experiment 6).

## Conclusions

1. **Don't pick parameters by maximizing a backtest.** It was tried honestly here and lost
   to the plain baseline out of sample in 8 of 8 cases.
2. **Keep the structure the data supports everywhere:** hold to the close, a ~1 ATR stop,
   top-1 stock, stop-limit entries.
3. **Candidate for validation, not adoption:** add "relvol ≥ 12" and "no entries after 10:30"
   (both have a reason and helped in both halves). Validate on untouched data (2016–2021) or
   forward on the IBKR paper account before trading it.
4. **Execution is the biggest lever.** Measured slippage costs more Sharpe (1.05 → 0.82) than
   any parameter adds. The paper account will tell us the real number.

## Reproduce

```bash
uv run python -m horizon_trader.intraday.orb_grid [--workers N] [--save]
```

`--save` adds the baseline and the best-on-train config to the dashboard (Backtests page,
names starting "ORB grid").

## Sources

- Schwarz, Barber, Huang, Jorion & Odean (2025), The Actual Retail Price of Equity Trades, Journal of Finance 80(5). https://ideas.repec.org/a/bla/jfinan/v80y2025i5p2507-2541.html
- Bailey & López de Prado (2014), The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Zarattini, Barbon & Aziz (2024), A Profitable Day Trading Strategy for the U.S. Equity Market. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
