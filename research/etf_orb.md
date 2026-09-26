# ETF ORB: QQQ, SPY, TQQQ, SPXL, UPRO, SOXL, SMH

Run 2026-09-25 with `uv run python -m horizon_trader.intraday.etf_orb`. Code:
`src/horizon_trader/intraday/etf_orb.py`. Raw results: `data/results/etf_orb.parquet`.

## Answer first

**No ETF version passes. ORB on liquid ETFs didn't work in 2021–2026, even before costs.**

- **Slippage is small on ETFs**: 0.5–2.2¢ on entries and 0.7–4¢ on stop-outs, as hoped. It's
  not what kills this. **The edge itself is weak in this period.**
- **The paper replication under its own assumptions** (its rules, $25k, $0.0005/share, no
  slippage) gives QQQ a Sharpe of **0.46** and TQQQ **0.53**, against the paper's 1.12 and 1.19
  for 2016 – Feb 2023.
- **At $5k on IBKR Tiered with measured slippage, 19 of 21 combinations lose money.** The
  exceptions are SOXL/SMH with Sharpe ≤ 0.46, which fail the both-halves test.
- **Buy and hold beat every version on every ticker.**
- **The paper's own after-the-fact "optimum"** (5% ATR stop, held to the close; reported as
  +9,350% on TQQQ) is the **worst** rule set everywhere: Sharpe −0.35 to −2.44 with measured
  slippage.

## The rules tested (confirmed against the paper's PDF)

Zarattini & Aziz (2023), *Can Day Trading Really Be Profitable?*, first posted 2023-04-24.
Pre-registered, 3 rule sets × 7 tickers = 21 combinations:

| Rule set | Entry | Stop | Exit |
|---|---|---|---|
| **A** paper 2023 (Table 1) | Market at the 9:35 open, direction of the first 5-minute candle | The first candle's low (long) / high (short) | 10R target or the close |
| **B** our stock baseline | Stop-limit at the first candle's high / low | 1 ATR from the fill | The close |
| **C** paper's section-4 optimum | Market at the 9:35 open | 5% of the 14-day ATR | The close |

Sizing as the paper: shares = min(1% of equity / R, 4 × equity / price). On a 3x ETF that
allows up to 12x the underlying index. Periods: train 2021-10 – 2023-12, test 2024-01 –
2026-09; plus before/after publication.

**Pass rule:** with measured slippage at $5k Tiered, Sharpe ≥ 0.5 in both train and test,
and positive after publication.

## Measured slippage (1-second bars, up to 300 trades per ticker and rule)

| Ticker | Entry at 9:35 (market) | Stop-outs, rule A | Stop-outs, rule B | Stop-outs, rule C |
|---|---|---|---|---|
| QQQ | 2.2¢ | 3.4¢ | 1.8¢ | 2.5¢ |
| SPY | 1.9¢ | 2.4¢ | 2.4¢ | 1.9¢ |
| TQQQ | 1.3¢ | 1.4¢ | 0.8¢ | 0.9¢ |
| SPXL | 0.5¢ | 3.2¢ | 2.0¢ | 3.2¢ |
| UPRO | 0.6¢ | 1.5¢ | 1.4¢ | 1.6¢ |
| SOXL | 0.5¢ | 1.0¢ | 0.7¢ | 1.1¢ |
| SMH | 0.6¢ | 3.2¢ | 3.4¢ | 4.0¢ |

- **Entry estimate:** half the 1¢ spread, plus any adverse average move in the second after
  9:35. QQQ and SPY show +1.4–1.7¢ of continuation in that second.
- **Stop-outs:** floored at zero, as for stocks, because they're triggered by price moving
  against us.
- **Size in context:** a few cents on a $100–700 share is 0.1–0.5 basis points, far below
  the ~14 bps measured on in-play stocks.
- **Surprise:** SPXL and UPRO are thin (~1M shares/day), yet their fills were fine.

## Results: measured slippage, $5k, IBKR Tiered

| Ticker | Rule | Sharpe | CAGR | Max DD | Sharpe 2021–23 | Sharpe 2024–26 | After publication | Pass |
|---|---|---|---|---|---|---|---|---|
| QQQ | A paper 2023 | −0.13 | −7.2% | −48% | −0.24 | 0.02 | −0.07 | no |
| QQQ | B stock baseline | −0.35 | −3.0% | −21% | −0.95 | 0.30 | −0.16 | no |
| QQQ | C paper optimum | −0.35 | −10.6% | −52% | −0.43 | −0.18 | 0.03 | no |
| SPY | A | −0.91 | −20.5% | −69% | −0.77 | −0.91 | −0.63 | no |
| SPY | B | −0.50 | −4.4% | −28% | −0.68 | −0.34 | −0.11 | no |
| SPY | C | −1.45 | −20.8% | −70% | −1.47 | −1.06 | −0.81 | no |
| TQQQ | A | −0.38 | −18.0% | −73% | −0.50 | −0.22 | −0.20 | no |
| TQQQ | B | −0.38 | −3.4% | −23% | −1.01 | 0.24 | −0.23 | no |
| TQQQ | C | −0.93 | −49.6% | −98% | −0.77 | −0.40 | −0.19 | no |
| SPXL | A | −0.47 | −21.3% | −77% | −0.04 | −0.86 | −0.35 | no |
| SPXL | B | −0.69 | −5.8% | −31% | −0.85 | −0.54 | −0.23 | no |
| SPXL | C | −2.44 | −61.3% | −99% | −1.89 | −0.53 | −0.44 | no |
| UPRO | A | −0.58 | −24.3% | −81% | −0.21 | −0.85 | −0.41 | no |
| UPRO | B | −0.77 | −6.5% | −30% | −0.77 | −0.68 | −0.42 | no |
| UPRO | C | −1.44 | −52.3% | −98% | −0.98 | −0.71 | −0.73 | no |
| SOXL | A | 0.14 | −1.1% | −55% | 0.79 | −0.50 | 0.10 | no |
| SOXL | B | 0.14 | 0.8% | −14% | −0.05 | 0.31 | 0.18 | no |
| SOXL | C | −1.18 | −61.5% | −99% | −0.95 | −0.80 | −0.92 | no |
| SMH | A | −0.03 | −5.7% | −55% | 0.44 | −0.48 | −0.19 | no |
| SMH | B | 0.46 | 3.2% | −14% | −0.33 | 1.21 | 0.69 | no |
| SMH | C | −0.35 | −18.8% | −67% | −0.81 | 0.09 | −0.07 | no |

Correlation with SPY is about 0 for all of them (−0.10 to +0.05). The best combination (SMH, B)
has a deflated Sharpe probability of 0.04 over 21 trials: not distinguishable from luck.

**By slippage scenario** (full-period Sharpe, $5k / $20k): even at 0¢ the best is SMH-B
(0.46 / 0.80) and SOXL-A (0.42 / 0.43). QQQ-A is 0.24 / 0.31 at 0¢. Slippage moves results by
0.1–0.5 Sharpe; it doesn't create or destroy an edge that isn't there.

## Paper replication (rule A, $25k, $0.0005/share, 0¢)

| Ticker | Sharpe | CAGR | Before publication | After publication | Win rate | Avg R |
|---|---|---|---|---|---|---|
| QQQ | 0.46 | 9.5% | 0.36 | 0.52 | 24% | 0.09 |
| TQQQ | 0.53 | 13.4% | 0.25 | 0.64 | 24% | 0.08 |
| SPY | −0.17 | −6.3% | −0.57 | 0.07 | 18% | −0.01 |
| SOXL | 0.73 | 21.8% | 0.92 | 0.64 | 28% | 0.12 |
| SMH | 0.37 | 7.1% | 0.68 | 0.23 | 27% | 0.04 |

The paper reports, for 2016 – Feb 2023: QQQ Sharpe 1.13 (24% win rate, avg 0.13R) and TQQQ
1.19 (avg 0.18R). Our win rate matches exactly (24%), but the average trade is about a third
smaller. Our overlap with the paper's period (Oct 2021 – Feb 2023) is short, so this says
the 2021–2026 environment was weaker, not that the paper is wrong about 2016–2020.

## Buy and hold, same period (price only)

| QQQ | SPY | TQQQ | SPXL | UPRO | SOXL | SMH |
|---|---|---|---|---|---|---|
| 16.1%, Sharpe 0.77 | 12.4%, 0.77 | 21.6%, 0.63 | 22.1%, 0.65 | 21.7%, 0.64 | 31.8%, 0.82 | 37.1%, 1.04 |

## What this means

- **The ETF version fails on edge, not execution.** The slippage problem that hurt the stock
  ORB mostly disappears on ETFs, but there isn't enough edge left to exploit in 2021–2026.
- **Stocks-in-Play works better because of the selection.** The relative-volume filter is
  the strategy. Without it (an ETF every day), ORB is roughly noise, the same conclusion the
  Stocks-in-Play paper reached (its unfiltered version: Sharpe 0.48).
- **Leveraged ETFs don't help.** TQQQ behaves like QQQ with more leverage; the 3x S&P ETFs
  are worse than SPY. The tight-stop version on 3x ETFs lost 50–60% a year.
- The one intraday ETF strategy that did hold up is a different one: **QQQ noise-area
  momentum** (see `research/strategy_survey.md` and `research/portfolio_mix.md`).

## Sources

- Zarattini & Aziz (2023), Can Day Trading Really Be Profitable? Evidence of Sustainable Long-term Profits from Opening Range Breakout (ORB) Day Trading Strategy vs. Benchmark in the US Stock Market. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622
- Zarattini, Barbon & Aziz (2024), A Profitable Day Trading Strategy for the U.S. Equity Market. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
