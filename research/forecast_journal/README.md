# Forecast journal: an LLM analyst team, scored forward

**Status:** built 2026-11-05, first run pending. **No result yet.** Rules:
[protocol.md](protocol.md), written before any run.

**Question:** can an LLM team that reasons about the market the way a discretionary trader does
(selloffs, leverage and margin calls, politics, the AI-capex story, what options already
price) make better-than-chance calls and option trades? A backtest can't answer it: the model
has read what happened afterwards (see [llm_fundamentals](../llm_fundamentals/README.md)). So
every view is written down before the outcome exists and scored automatically. It never places
an order.

Design adapted from [TradingAgents](../tradingagents/README.md)
([arXiv 2412.20138](https://arxiv.org/abs/2412.20138)): separate analysts and a bull/bear
debate, but risk is enforced by code and the evidence is forward only.

## Pipeline (one run = 8 `claude -p` calls)
1. **Market packet** (code, `agents/market.py`): 21 ETFs (market, sectors, rates, credit,
   dollar, gold, oil, bitcoin) with 1/5/20-day returns, moving-average distance, 20-day vol
   and distance from the 52-week high; VIX and VIX3M term structure; HYG/IEF as a credit
   gauge; options-implied ~1-week moves (ATM straddle) for SPY, QQQ, IWM and SMH.
2. **Analysts** (parallel): market (packet only, no tools), news and macro (web), earnings
   (web). Each must date and source every fact; web results from earlier years are discarded.
3. **Debate:** a bull case and a bear case, then a rebuttal from each side.
4. **Trader** (JSON schema): regime, bias, thesis, invalidation, debate winner; mandatory
   SPY/QQQ calls at 1, 5 and 20 days plus up to 4 optional; 0-3 trade specs; positions to close.
5. **Code takes over** (`agents/book.py`): resolve each spec to listed contracts, check quotes
   and risk caps, open the idea and its mirror, mark everything, close at horizon or expiry,
   score.

## Running it
```bash
uv run python -m horizon_trader.agents.journal run      # weekdays ~15:00 ET (live option quotes)
uv run python -m horizon_trader.agents.journal score    # mark/close/rescore without a new decision
uv run python -m horizon_trader.agents.journal report   # scorecard in the terminal
```
Scheduled by `deploy/windows/install_tasks.ps1` (job `horizon-trader journal`, weekdays 15:00
machine time, which assumes the PC is on New York time like the other jobs). The PC must be on
and logged in to Claude Code. Usage per run: 3 Sonnet analyst calls (2 with web search) and 5
Opus calls; each role's cost is logged in `raw/<role>.json` and shown on the dashboard.

Option bid/ask: live IBKR quotes first (IB Gateway must be running and logged in at 15:00;
read-only, client id 31), Yahoo's ~15-minute-delayed quotes as the per-contract fallback.
Every priced leg stores `quote_source` (`ibkr` or `yahoo`), and implied moves say
`mid, ibkr` or `mid, yahoo`.

Outside market hours Yahoo shows 0/0 option quotes, so ideas are rejected ("no live quote")
while the reasoning and forecasts are still logged.

## Files (`data/journal/`, git-ignored)
- `days/<date>/`: `packet.md`/`.json`, `reports/<role>.md`, `raw/<role>.prompt.md` and
  `raw/<role>.json` (the full `claude -p` output: model, cost, turns), `decision.json` (the
  trader's answer, problems, how each idea was priced or why it was rejected).
- `forecasts.csv` (every call with `prompt_sha` and model), `scored_forecasts.csv`,
  `book.json` (positions and mirrors), `marks.csv` (each run's mark per position),
  `summary.json`.
- `data/live/journal_shadow/equity.csv` + `state.json`: the ideas' hypothetical $10k book, so
  it shows on the Live page next to the other forward tests.

Dashboard: the **Journal** page (scorecard, each day's brief, forecasts, ideas, the full
reports and debate, the book).

## Log
| Date | Notes |
|---|---|
| 2026-11-05 | Built and unit-tested with a fake market and a fake Claude; not yet run for real. |
