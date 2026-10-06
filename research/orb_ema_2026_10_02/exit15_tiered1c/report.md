# Tiered, 1-cent slippage, and 15-minute EMA exits

**Slower EMA exits improve the strategy, but the unchanged ORB still leads.**
With identical ORB entries, switching the exit from a 5-minute EMA to a 15-minute
EMA increases net CAGR from **-3.27% to +4.42%**. Holding to the close unless the
ATR stop is hit returns **16.82%** under the same Tiered/1c assumptions.

The owner requested this follow-up after the first test. We fixed the changes in
the [protocol](protocol.md) before this run. Entry rules still use **5-minute**
candles; only exits use **EMA(12) of completed 15-minute closes**. The fixed ATR
stop remains active between EMA decisions, including before 09:45.

## Same-cost comparison

Sample: **2021-10-22 through 2026-10-01**, all **1,240 sessions**, no exclusions.
Each simulation starts with **$5,000**, risks 1% of starting-day equity, uses whole
shares and a 2x entry-notional ceiling. The main stop is **1 prior 14-day daily
ATR**. Net results use IBKR Pro Tiered plus **$0.01/share adverse slippage on
entry and non-auction exits**. Closing auctions retain commissions and zero
additional modeled slippage.

| Rule | Net CAGR | Zero-hurdle Sharpe | Max drawdown |
| --- | ---: | ---: | ---: |
| ORB: stop or hold until close | 16.82% | 0.93 | -21.11% |
| Same ORB entries, 5-minute EMA exit | -3.27% | -0.25 | -24.68% |
| Same ORB entries, 15-minute EMA exit | 4.42% | 0.36 | -19.71% |

The slower exit trims worst drawdown by about 1.4 percentage points relative to
holding, at a cost of about 12.4 percentage points of annualized return in this
sample. Its result is positive in both independent restarts: **3.01%** CAGR in
2021-23 and **5.20%** from 2024 onward. The ORB control returns **12.50%** and
**19.94%**, respectively.

The other two entry rules also improve at 1 ATR:

| Entry rule, held fixed | 5-minute exit net CAGR | 15-minute exit net CAGR |
| --- | ---: | ---: |
| 5-minute range-break close + 5-minute EMA confirmation | -3.55% | 2.07% |
| 5-minute EMA direction on the ORB-selected stock | -6.15% | 4.34% |

The selected-stock EMA rule is less consistent across time: **-7.12%** in the
first restart and **14.77%** in the second with the slower exit. EMA confirmation
returns **-0.47%** and **4.21%**. These are reused historical subsamples.

## What changed

All **21,970 raw entries** across four rules and five stop widths match the first
run exactly, including direction, time, price and stop distance. The control's
5,005 round trips across stop widths have identical exits too. This separates
the effect of slower exits from the change in cost assumptions.

At the main 1-ATR setting, mean gross profit per ORB trade rises from **0.027R to
0.063R**, against **0.115R** for the hold-to-close control. Average holding time
rises from **54 to 127 minutes**, versus **272 minutes** for the control. Slower
exits retain more of the move but still surrender some continuation gains.

Before any fees or slippage, CAGR is **4.76%** with 5-minute exits, **12.12%**
with 15-minute exits, and **23.75%** for the control. The change helps even before
costs; the remaining shortfall is not solely a commission issue.

## Stop widths

Full-period **Tiered/1c net CAGR**, with 15-minute EMA exits where applicable.
Risk stays at 1%, so wider stops buy fewer shares.

| Stop, daily ATR | ORB hold | ORB + EMA exit | EMA confirmation entry | Selected-stock EMA entry |
| --- | ---: | ---: | ---: | ---: |
| 0.50 | -2.66% | -11.16% | -3.21% | 6.84% |
| 0.75 | 10.73% | 1.98% | -0.48% | 3.30% |
| 1.00 | 16.82% | 4.42% | 2.07% | 4.34% |
| 1.50 | 10.59% | 3.83% | -0.24% | 2.67% |
| 2.00 | 7.54% | 2.03% | 1.49% | 0.46% |

The preselected 1-ATR main setting remains the highest full-period CAGR for the
ordinary ORB and its exit-only variant among these five widths. No EMA setting
in this grid exceeds the ordinary 1-ATR ORB control. We have not selected a new
setting based on the grid.

## Validation and limits

- **48 targeted tests pass**, including separate entry/exit signal clocks,
  true 15-minute EMA calculation, incomplete-candle/truncation checks, mirrored
  shorts, continuous protective stops, missing next-minute fills, and Tiered/1c
  fees on both sides. Ruff passes on changed Python files.
- Fourteen distinct delayed EMA exit events were reconstructed from the cached
  bars. Each used the first available open after a completed adverse 15-minute
  signal; no missing-minute fill price was invented.
- Original candidate/split source hashes and sample dates match. The complete
  calendar is retained, including no-trade days. Saved results include all
  **240** combinations of timeframe, rule, stop width, costs and period.
- One cent is the requested assumption, not a new measurement. This is a
  standalone historical market-order model, not the prior stop-limit study or
  shared-account simulation. It excludes short-locate/borrow costs, subscription
  costs, and broker margin liquidation. Stops remain anchored to raw fills;
  entry/exit slippage can take losses beyond the nominal risk budget.
- Five prior sessions warm the EMA on today's split basis. Missing candle-end
  minutes are skipped. The sample has been reused; these results are not fresh
  validation or broker-certified execution.

Research defaults now use Tiered/1c. No execution settings or scheduled tasks
were changed and no orders were submitted.

[Every comparison](comparison.csv), [new-run metrics](metrics.csv),
[equity curves](equity_1atr.csv), [trade diagnostics](trade_details_1atr.csv),
[verification](verification.json), [manifest](manifest.json).

```powershell
.venv/Scripts/python.exe -m horizon_trader.intraday.orb_ema --candle-minutes 5 --exit-candle-minutes 15 --plan tiered --slippage 0.01 --output research/orb_ema_2026_10_02/exit15_tiered1c
.venv/Scripts/python.exe research/orb_ema_2026_10_02/exit15_tiered1c/compare.py
.venv/Scripts/python.exe -m pytest tests/test_orb_ema.py tests/test_orb.py tests/test_ema_vwap.py -q -p no:cacheprovider --basetemp data/tmp/orb_ema_tests
```
