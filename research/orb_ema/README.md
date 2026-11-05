# ORB plus 12-EMA momentum management (2026-10-02)

**2026-10-03 follow-up:** [two-close confirmation, narrower stops and sizing](confirmation_risk/README.md).
With the same entries, Tiered/1c costs and 1% risk, waiting for two adverse
15-minute EMA closes lifts 1-ATR CAGR from 4.42% to **6.07%**, versus **16.82%**
for original ORB. Tightening the two-close stop to **0.5 daily ATR** raises
stop-outs from **21.4% to 46.2%** and drops CAGR to **-12.87%**. Doubling risk
to 2% at that narrower stop produces **-26.98% CAGR and 85.30% drawdown**.
Raising the 2x cap to 4x has little effect because risk-based sizing usually
binds first. All 24 configurations are retained; no operational settings changed.

**Exit-path diagnosis:** [stop timing and post-exit continuation](exit_diagnostics/README.md)
on the same 1,001 entries. Original ORB stops 31.5% of trades, versus 17.7% with
15-minute EMA exits. Among those 654 EMA exits, 37.6% later move another 0.5R
before the original stop, and holding finishes better after costs 49.8% of the
time. The larger surrendered gains outweigh the saved losses. The original
stop occurs a median 32 minutes after entry. No new exit rules were fitted.

**Cost and candle settings:** the owner specified **Tiered commissions, 1c slippage and
15-minute EMA exits**, retaining 5-minute entries. At the same 1-ATR stop and $5k,
the exit-only version improves from **-3.27%** CAGR with 5-minute exits to
**+4.42%** with 15-minute exits. The unchanged ORB control returns **16.82%**
under those same costs. All 21,970 entries across the grid match the original run.
See the [Tiered/1c follow-up](exit15_tiered1c/README.md).
These are the default cost assumptions for subsequent ORB research.

## First experiment (earlier cost assumptions)

The owner proposed a 12-EMA direction/exit rule on 5-minute candles with a 1-ATR
stop, plus stop-width experiments. The ATR is the existing prior 14-day daily ATR.

The [completed report](report.md) compares ORB hold-to-close,
the same entries with EMA exits, range-break close plus EMA confirmation, and
EMA direction on the ORB-selected stock. All use one trade/day and completed
signals filled at the next open.

On 1,240 sessions, 2021-10-22 through 2026-10-01, the exit-only change cuts mean
gross profit from 0.115R to 0.027R. At $5k, 1 ATR, Fixed fees plus assumed 5c
slippage, CAGR drops from +1.1% to -26.1%; Tiered from +5.8% to -17.0%.
All three EMA variants lose after modeled costs at every stop in
{0.5, 0.75, 1, 1.5, 2} ATR. These are market-order research assumptions, not the
old measured stop-limit experiment or broker-verified fills.

The gross deterioration matters: there are fewer stop-outs, but EMA exits also
cut large winners. The tested rules do not justify replacing the baseline exit.
No live/paper settings were changed.

Code: `src/horizon_trader/intraday/orb_ema.py`.
[Frozen protocol](protocol.md),
[all metrics](metrics.csv),
[verification](verification.json).
