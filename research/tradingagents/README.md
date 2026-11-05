# TradingAgents (Xiao et al. 2024): a multi-agent LLM trading firm

**Verdict:** a useful architecture with no usable evidence. The paper models an LLM team on a
trading firm and reports Sharpe 5.6-8.2 over **one quarter, on three stocks, with no
transaction costs**, against baselines (MACD, RSI, SMA) that our own tests found below
buy-and-hold. We borrow two ideas, the bull/bear debate and separate analysts with structured
reports, for the [forecast journal](../forecast_journal/README.md), and test them forward
instead of trusting the paper's backtest.

Paper: [arXiv 2412.20138](https://arxiv.org/abs/2412.20138) (v7, June 2025). Reviewed
2026-11-05 from the paper only; the open-source code was not run.

## How it works
1. **Analysts**, each writing its own report: fundamentals (statements, earnings, insider
   trades), sentiment (Reddit, X, scored by auxiliary models), news (Bloomberg, Yahoo, EODHD,
   Finnhub) and technicals (prices plus about 60 indicators).
2. **Bull and bear researchers** read the reports and debate for several rounds.
3. **A trader** weighs the debate and decides buy, sell or hold.
4. **A risk team** (aggressive, neutral, conservative agents) reviews it; a fund manager
   approves.

Agents exchange structured reports rather than one long chat. Quick models (gpt-4o-mini,
gpt-4o) fetch and summarize; o1-preview does the reasoning and decisions. One stock-day costs
about 11 LLM calls and 20+ tool calls, which is why the backtest is short.

## Reported results (Table 1, 2024-01-01 to 2024-03-29)
| Stock | TradingAgents return / Sharpe / max DD | Buy and hold |
|---|---|---|
| AAPL | +26.6% / 8.21 / 0.9% | -5.2% / -1.29 / 11.9% |
| GOOGL | +24.4% / 6.39 / 1.7% | +7.8% / 1.35 / 13.0% |
| AMZN | +23.2% / 5.60 / 2.1% | +17.1% / 3.53 / 3.8% |

## Why these numbers aren't evidence
- **Sample:** about 60 trading days on 3 stocks: one market regime. The setup lists five
  stocks (AAPL, NVDA, MSFT, META, GOOGL) but the table reports AAPL, GOOGL and AMZN, without
  explanation.
- **No costs:** commissions and slippage aren't mentioned for a daily buy/sell/hold strategy.
  Costs alone killed several daily rules here (see `research/ema_vwap/README.md`).
- **Weak baselines:** MACD, KDJ/RSI, zero-mean reversion and SMA. No momentum baseline, no
  repeated runs to show run-to-run variance of a stochastic LLM.
- **The authors flag it themselves:** the Sharpe is "above expected", attributed to few
  pullbacks in the window. Over 3 months a Sharpe of 8 is mostly noise.
- **Lookahead:** the test window starts after the models' training cutoff (October 2023),
  better than most LLM-trading papers, but the paper doesn't discuss contamination, and the
  news tools could still retrieve later articles.

Same pattern as the [Papers With Backtest audit](../pwb/README.md): a good idea and a
flattering test.

## What we took, what we left
| TradingAgents | Forecast journal |
|---|---|
| Separate analysts | Market (packet only), news and earnings (web search) analysts |
| Bull/bear debate | Bull and bear cases plus one rebuttal round each |
| LLM trader decides | LLM trader writes forecasts and trade **specs**; code prices them |
| LLM risk team | **Code** enforces risk: premium caps, defined risk only |
| 3-month backtest, no costs | Forward only, scored after 5 and 20 days, ask/bid fills, vs mirror trades |
| Daily single-stock trading | Market-level calls and a few multi-day option trades |
