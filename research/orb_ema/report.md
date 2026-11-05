# ORB with a 5-minute 12-EMA: first results

**The tested EMA rules weaken this ORB strategy.** Keeping the same entries and
replacing the close exit with an adverse EMA close cuts mean gross profit from
**0.115R to 0.027R** per trade. The EMA variants lose after both modeled commission
plans at every tested ATR stop width. This does not establish that every momentum
exit fails; it rejects these particular rules on the reused sample.

Run 2026-10-02. Local sample: **2021-10-22 through 2026-10-01**, 1,240 sessions,
zero excluded sessions. The owner confirmed 5-minute candles. Rules were written
in the [protocol](protocol.md) before this run; all 20 signal configurations and
180 cost/period summaries remain in [metrics.csv](metrics.csv).

## Primary 1-ATR comparison

Each simulation starts at $5,000, risks 1% per trade, uses whole shares, and caps
entry notional at 2x equity. One round trip per selected stock/day. Stop distance
is the prior 14-day **daily** ATR, not a five-minute ATR. Gross removes all fees
and slippage. Net uses the repository commission schedules plus assumed **5 cents
per share on entry and every non-auction exit**. Auction exits pay commission
but have no additional modeled slippage.

| Rule | Gross CAGR | Fixed net CAGR | Tiered net CAGR | Fixed max drawdown | Fixed Sharpe |
| --- | ---: | ---: | ---: | ---: | ---: |
| ORB, fixed stop or hold to close | 23.75% | 1.14% | 5.78% | -30.55% | 0.15 |
| Same ORB entries, EMA exit | 4.76% | -26.13% | -17.03% | -78.43% | -2.74 |
| Range-break close + EMA confirmation, EMA exit | 5.47% | -30.68% | -19.25% | -83.87% | -3.37 |
| EMA direction on the ORB-selected stock, EMA exit | 3.55% | -37.30% | -22.86% | -90.09% | -2.97 |

Sharpe uses a zero cash hurdle. These are standalone market-order simulations,
not the prior stop-limit experiment and not the shared-account replay. The older
12.2% Tiered CAGR used different fill assumptions and sample dates. This run
does not revise that number on a like-for-like basis.

## What the exit changes

The exit-only variant has exactly the same 1,001 entries as its control. EMA
management lowers the stop-out fraction from **31.5% to 12.7%**, and average
holding time from **272 to 54 minutes**. It improves gross outcomes on 439 trades,
worsens them on 422, and leaves 140 unchanged. Counting better trades is therefore
misleading: the lost gains are larger than the saved losses in aggregate.

For example, the five biggest control winners finish as follows; these examples
explain the mechanism and were selected after the run, not used to tune a rule:

| Date | Stock | ORB gross R | With EMA exit, gross R |
| --- | --- | ---: | ---: |
| 2026-08-19 | MRNA | 13.86 | 5.35 |
| 2024-10-07 | SRRK | 9.71 | 5.30 |
| 2025-01-03 | CRNC | 8.88 | 6.30 |
| 2024-02-27 | IFBD | 7.75 | 2.14 |
| 2023-03-07 | PTGX | 7.04 | 3.31 |

The EMA can react to a pullback before the broader move is finished. Conversely,
waiting for a completed close and the next fill necessarily gives back some
movement. Moving averages cannot identify exact tops or bottoms; see
[Fidelity's EMA explanation](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/ema).
Here the gross result already deteriorates, and fees plus the additional
non-auction exit slippage consume the remaining small edge. An EMA exit can also
realize a loss; it is not inherently a take-profit order.

## Stop-width sensitivity

Full-period net CAGR, **Fixed / Tiered**, with the same 1% nominal risk budget.
Larger stops reduce shares; the table does not hold position size constant.

| Stop, daily ATR | ORB hold | ORB + EMA exit | ORB + EMA confirmation | Selected-stock EMA |
| --- | ---: | ---: | ---: | ---: |
| 0.50 | -31.0% / -23.9% | -55.8% / -39.9% | -59.3% / -41.3% | -61.2% / -40.0% |
| 0.75 | -7.8% / -3.9% | -32.9% / -23.2% | -41.1% / -26.9% | -50.1% / -30.2% |
| 1.00 | 1.1% / 5.8% | -26.1% / -17.0% | -30.7% / -19.3% | -37.3% / -22.9% |
| 1.50 | -0.7% / 4.3% | -19.7% / -12.1% | -24.9% / -15.0% | -27.5% / -16.6% |
| 2.00 | -2.3% / 3.1% | -17.5% / -10.0% | -19.7% / -11.0% | -24.3% / -14.0% |

Widening the stop reduces the EMA strategies' loss rate by reducing exposure;
it does not restore positive net expectancy in this test.

## Separate account restarts

Primary 1-ATR Fixed case; each subperiod starts at $5,000. These are reused
historical subsamples, not untouched out-of-sample evidence.

| Rule | 2021–23 CAGR | 2024 onward CAGR |
| --- | ---: | ---: |
| ORB hold | -2.44% | 4.67% |
| ORB + EMA exit | -23.25% | -19.63% |
| ORB + EMA confirmation | -26.73% | -22.19% |
| Selected-stock EMA | -29.12% | -26.95% |

## Validation and limits

- All 1,001 baseline entry and exit prices reproduce the existing conservative
  ORB simulator. The exit-only variant preserves every entry time and price.
- **37 tests pass**, covering EMA causality, unfinished candles, split adjustment,
  mirrored shorts, next-open fills, gap stops, same-minute ordering, early closes,
  no reentry, whole-share sizing, costs and flat days. Ruff passes on new code.
- All 1,240 local sessions in the sample appear in the portfolio calendar.
  [Verification](verification.json) and [manifest](manifest.json) retain checks
  and source/dependency hashes; the input cache records file sizes/timestamps.
- New signal-time spreads are not measured. Five-cent slippage is an assumption,
  not a bound or a fill forecast. No locates, borrow costs, subscription charges,
  historical broker restrictions, intraday margin liquidation, or joint-account
  funding are modeled. Stops are based on the raw entry, with slippage adding to
  nominal 1% risk. Early closes use a SPY coverage proxy.
- Five prior regular sessions seed the EMA on today's split basis. Candles missing
  their final minute are skipped, so a sparse stock may differ from a chart that
  carries stale closes. At most one daily trade; reversals/reentries, EMA slope
  filters and intraday-ATR stops were not tested.

No execution settings or scheduled tasks were changed, and no orders were sent.

```powershell
.venv/Scripts/python.exe -m horizon_trader.intraday.orb_ema --exit-candle-minutes 5 --legacy-costs --output research/orb_ema
.venv/Scripts/python.exe research/orb_ema/verify.py
.venv/Scripts/python.exe -m pytest tests/test_orb_ema.py tests/test_orb.py tests/test_ema_vwap.py -q -p no:cacheprovider --basetemp data/tmp/orb_ema_tests
```

Raw selected-stock paths and round trips stay in the ignored
`data/orb_ema_2026_10_02/` directory. Headline results and every sensitivity are
saved here for review.
