# Forecast journal: pre-registered protocol

Written 2026-11-05, before the first run. Changing a rule below after results exist starts a
new test; record the date and reason under "Amendments".

## What is tested
1. **Market calls.** Every run must give a direction (up/down) and a confidence (1-5) for SPY
   and QQQ over 5 and 20 trading days, close of the run day to close N trading days later
   (adjusted closes). These four "mandatory" calls are the primary test because they exist
   every day and can't be cherry-picked. Optional calls (up to 4, any ticker, optionally vs
   SPY) are reported separately.
2. **Trade ideas.** 0-3 specs a day (long call/put, call/put debit spread, long shares),
   priced by code from the live option chain: bought at the ask, sold at the bid, $0.65 per
   contract (an assumption: IBKR Pro list; Alpaca charges less). Each opened idea gets a
   **mirror** opened at the same moment in the opposite direction with the same spec and
   sizing. Positions close at their horizon, at expiry, or when the trader closes them.

## Baselines
- Calls: **always-up**, the hit rate you'd get by calling "up" on the same forecasts
  (relative calls: the ticker beating SPY). Beating 50% means nothing in a rising market.
- Ideas: **their mirrors.** If ideas and mirrors both lose about the same, the option
  structure (time decay, spread) explains the result and the direction carried no information.
- Doing nothing: ideas must make money after costs.

## Decision rules
Evaluated at 60 completed run days (about 3 months) and again at 120.
- **Calls PASS:** mandatory 5-day calls hit at least 5 percentage points above always-up, and
  the mean edge (signed return in the called direction) is > 0 with t > 1 on the
  non-overlapping subsample (every 5th call per ticker).
- **Ideas PASS:** at least 30 closed idea/mirror pairs, idea P&L after costs > 0, and ideas
  beat their mirrors with t > 1 (paired by idea).
- **KILL at 60 days:** mandatory 5-day hit rate at or below always-up and mean edge <= 0. Ideas
  are killed after 30 closed pairs if their P&L is negative and below the mirrors'.
- Anything still short of PASS at 120 days is dead.
- **On an ideas PASS:** the same specs go to Alpaca paper (paper endpoint only, same risk
  caps), with the journal continuing alongside as the comparison.

## Fixed setup
- Schedule: weekdays at 15:00 ET (`deploy/windows/journal.ps1`). A missed day stays missed:
  `run` only accepts today's New York date and a finished day is never rebuilt.
- Roles and models: every role on `gpt-6.1-sol` via `codex exec` (see the 2026-11-05
  amendment; originally analysts `claude-sonnet-5-5`, debate and trader `claude-opus-5-5` via
  `claude -p`). News and earnings analysts get live web search; market, debate and trader get
  no tools. No saved session, no user config or MCP servers, a read-only sandbox, run from an
  empty temp directory so the repo's CLAUDE.md/AGENTS.md don't enter the prompt.
- **A different model or any edit to `agents/prompts.py` (its `prompt_sha`) is a new test
  segment.** Every forecast row stores `prompt_sha` and `model`; evaluate segments separately
  (`summary.json` pools them, so split `scored_forecasts.csv` by `prompt_sha` when evaluating).
- Risk rules (`agents/book.py:Rules`): $10k hypothetical account, $150 premium per idea, $600
  total open premium, $2,500 per shares idea, at most 3 new and 8 open ideas, legs quoted
  wider than 30% of mid rejected, defined risk only.

## Known limits (accepted up front)
- **Power is low.** 60 days give ~12 non-overlapping 5-day calls per ticker: a real 60% hit
  rate can't be told from 50% at that size. The 60-day check guards against an obviously bad
  signal; only the 120-day check (or longer) can support a good one.
- Option bid/ask come from live IBKR quotes when Gateway is up (OPRA, read-only), else
  Yahoo's ~15-minute-delayed quotes, per contract. Each priced leg records `quote_source`;
  fills at a delayed ask/bid are approximate, so split results by source if both occur.
- `exit_planned` counts weekdays and ignores holidays; a position may close a day early.
- Web research isn't reproducible: the analysts' searches are logged as their reports, not as
  raw pages. Neither `claude -p` nor `codex exec` can set temperature, so a rerun would differ.
- Codex's web search only works through its code-mode host, so the two web analysts also get
  read-only code execution (no shell, in an empty temp directory).
- The bull/bear debate is one round plus a rebuttal each; more rounds were not tested.

## Amendments
- 2026-11-05, before the first run (no journal day existed): **1-day calls added.** The
  mandatory calls are now SPY and QQQ at 1, 5 and 20 trading days (close today to close
  tomorrow for the 1-day). The 5-day calls stay the primary test. The 1-day calls are
  secondary: telling a real 55% hit rate from 50% takes about 400 calls, so they get no PASS
  before ~400 run days; they are KILLED at 120 run days if their hit rate is at or below
  always-up. A split by scheduled macro event days (CPI, jobs, FOMC) is exploratory only.
- 2026-11-05, before the first run (no journal day existed): schedule moved from 15:30 to
  15:00 ET. Reason: the Alpaca competition follower (`agents/competition.py`) executes the
  ideas right after the journal finishes, and a 10-15 minute run starting at 15:30 left too
  little time for day orders before the close. Nothing else changed.
- 2026-11-05, before the first run: option bid/ask for the legs the book prices and marks,
  and for the packet's implied moves, come from live IBKR quotes first
  (`datasources/ibkr_quotes.py`), falling back to Yahoo per contract. Expiries, strikes,
  IV and daily closes still come from Yahoo. Reason: Yahoo's quotes are ~15 minutes old,
  and the Alpaca follower trades against the same live quotes. `--no-ibkr` restores
  Yahoo only.
- 2026-11-05 ~08:20 ET, before the first run (no journal day existed): **model changed from
  Claude (Sonnet analysts, Opus debate and trader) to `gpt-6.1-sol` for every role**, run
  through the Codex CLI on the owner's ChatGPT login (`llm/codex.py`, reasoning effort
  `high`). Reason: to save the owner's Claude usage. The prompts, schema and rules are
  unchanged (`prompt_sha` is the same); OpenAI's structured output adds
  `additionalProperties: false` to each schema object, which allows the same answers. Claude
  IDs still work (`--model claude-...`), and switching back would start a new segment.
