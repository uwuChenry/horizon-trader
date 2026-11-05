# Claude fundamental scores, monthly forward test (started 2026-10-01)

Code: `llm/fundamentals.py`, with data from `datasources/sec.py`. Background: item #1 in
[llm_strategies_survey.md](../llm_strategies_survey/README.md) and the "time capsule" design of
[Lehner & Lopez-Lira (2026)](https://arxiv.org/abs/2604.21433), who scored stocks with frozen
ChatGPT snapshots on fundamentals only.

**Status:** pre-registered, first scores on 2026-10-01. **No result yet.** The first
one-month returns arrive around 2026-11-02, and the verdict needs at least 12 monthly runs
(late 2027).

## Why forward only
Claude has read the internet up to its training cutoff. Scoring past quarters would let it
"predict" what it already knows happened, so a backtest can't be trusted
([The Memorization Problem](https://arxiv.org/abs/2504.14765)). Every score is logged with a
timestamp and model ID **before** the returns exist, and past months are never back-filled.

## What Claude sees (all filed before the as-of date)
For each of the 200 largest US companies (Massive point-in-time market caps on the last
trading day before the as-of date):
- **The last 8 fiscal quarters from SEC XBRL, as first reported:** revenue, growth vs the same
  quarter a year earlier, gross and operating margin, operating and net income. Fiscal Q4 =
  the annual figure minus Q1-Q3. Restatements are ignored, so the numbers are what investors
  saw at the time.
- **The latest balance sheet:** cash, long-term debt, assets, equity.
- **The latest earnings press release** (8-K item 2.02, exhibit 99), when it's newer than the
  last 10-Q/10-K. Results reach the 8-K weeks before the 10-Q. Micron's FQ4 2026 release from
  2026-09-30 is in the first run.
- **The start of the MD&A section** of the latest 10-Q/10-K (up to 10,000 characters).
- **No prices, market caps or valuation multiples.** The score rates the business, not the
  stock.

## The prompt and the schema
`GUIDE` and `SCHEMA` in the module are the prompt and the output schema. Their hash is logged
as `prompt_sha`.
- One score from 1 to 10 overall, plus growth, profitability, balance sheet and outlook.
- A direction (improving / stable / deteriorating) and a reason of at most 40 words.
- The scale is absolute across batches: about 10% of companies score 8 or more, and about 10%
  score 3 or less.
- Companies are shuffled into 20 batches of 10 (seeded by the date) so each batch mixes
  sectors.

## Two ways to score, same output files
- **Claude Code subagents.** Each reads `batches/batch_NN.md` and writes
  `scores/batch_NN.json`. Used for the first run: 20 subagents on `claude-opus-5-5`.
- **`run`: headless `claude -p`** with the model pinned, a JSON schema, all tools off
  (`--tools ""`, `--strict-mcp-config`) and no saved session. It uses the owner's Claude
  login, so no API key. It can't set temperature, so reruns may differ slightly; that's why
  the raw output is always logged.

`check` validates every batch (all tickers present, 1-10 integers, a valid direction) and
writes `scores.parquet`. A month directory is never rebuilt: `export` refuses if one exists.

## Pre-registered evaluation (fixed 2026-10-01)
- **Signal:** `score`, with ties broken by the sum of the four sub-scores.
- **Returns:** from the close of the first trading day after the as-of date. The primary
  horizon is 21 trading days; the secondary is 63.
- **PASS** after at least 12 monthly runs: the mean 1-month rank IC is > 0 with t > 1, **and**
  the top 20 by score beat the 200-name equal-weight universe on average monthly return.
- **KILL:** a mean 1-month rank IC ≤ 0 after 12 runs.
- **A different model is a new test.** The model ID is stored with every row.
- **Companies with no filings are excluded** (added 2026-10-01, after scoring but before any
  return existed). Foreign 20-F filers get no quarterly table and no filing text, so their
  score rests on general knowledge only. `check` flags them (`has_filings`) and `evaluate`
  leaves them out.
- **Power:** a realistic IC of 0.02-0.05 takes years to prove. Twelve months mainly guards
  against trusting a bad signal.

## Monthly routine
```bash
uv run python -m horizon_trader.datasources.massive download --dataset day   # latest prices/caps
uv run python -m horizon_trader.llm.fundamentals export               # as of today
uv run python -m horizon_trader.llm.fundamentals run                  # or score with subagents
uv run python -m horizon_trader.llm.fundamentals check
uv run python -m horizon_trader.llm.fundamentals evaluate
```
Run it on the first trading day of each month.

## Log
| As of | Universe date | Backend / model | Notes |
|---|---|---|---|
| 2026-10-01 | 2026-09-30 | 20 Claude Code subagents, claude-opus-5-5 | first run; all 20 batches valid; AZN, NBIS, SPOT, NU excluded (no filings) |
| 2026-11-05 | 2026-11-04 | `claude -p`, claude-opus-5-5 | 3 trading days late (missed the 2nd: not scheduled yet; now automatic in the morning job). 15 batches scored ~03:40 ET; 16-20 failed on the Claude usage limit and were scored ~06:55 ET, still before any return in the test window. All 20 valid; AZN, SPOT excluded (no filings). Top 20: NVDA, PLTR, MU, SNDK, ANET, WDC, MSFT, STX, AVGO, MPWR, ADI, LRCX, APH, APP, LLY, VRT, PWR, HWM, GEV, REGN |

### First run, descriptive only (no returns yet)
- **Score distribution:** 2 (2), 3 (6), 4 (10), 5 (30), 6 (51), 7 (52), 8 (28), 9 (20),
  10 (1). That's 24.5% at 8 or more against the ~10% the prompt asked for. Calibration drifts
  upward across agents, but the test uses ranks, so levels don't matter.
- **Top 20:** PLTR, MU, SNDK, NVDA, MSFT, ALAB, TER, ANET, ISRG, FIX, AVGO, LLY, LRCX, GOOGL,
  APP, ADI, V, STX, MA, APH. Mostly AI hardware.
- **Bottom:** MSTR and MRNA at 2. CMCSA, ELV, QCOM, UPS, BA and WBD at 3.
- **Overlap with known signals:** the rank correlation of the score with 12-1 momentum is
  0.21, with the last 3 months' return -0.02, and with the growth sub-score 0.77. The score
  is mostly "revenue growth", partly momentum. If it ever passes, check that it adds something
  beyond momentum and growth.
- **Data check:** an agent flagged Lumentum's -$7.2B quarterly net loss. That is real: the
  FY2026 10-K reports -$6,935M net income (non-operating; Q4 operating income was +$279M), so
  the derived Q4 is correct.
