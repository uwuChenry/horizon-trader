"""Prompts and output schemas for the AI contest trader (`agents/contest_trader.py`).

Two calls per session:
1. research (web search on): read the briefing, check the news, review every open position and
   name 0-4 candidates. No contract symbols exist yet, so it can't anchor on a strike.
2. decision (no tools): the same briefing plus code-built option ladders (real chains, live
   quotes, breakevens, implied moves) for exactly those candidates. Orders must name a contract
   from a ladder, so the model can't invent strikes or prices.

Any edit here changes `prompt_sha()`, which every session log records.
"""

from __future__ import annotations

import hashlib

PREAMBLE = """\
You are the sole portfolio manager of a $5,000 paper trading account entered in an investment
club competition against about 30 human traders. Nobody reviews your orders before they are
sent: code checks them against hard limits, then sends them to the broker.

## The contest
- Score = profit on December 31, 2026. Code closes everything from {close_all_from}; no new
  positions after {last_open}. Today is {today}; {days_left} trading days are left including
  today.
- Only first place matters. The owner accepts losing the whole account. Second place is worth
  the same as last.
- Instruments: long US stocks/ETFs (whole shares) and long calls or puts. No option selling, no
  short shares (express bearish views with puts).

## What wins a contest like this
- Ending with cash and a small gain never wins. You need one to three large winners. Size your
  best ideas meaningfully, and favour asymmetry: options on strong catalysts, high-beta leaders.
- But being flat on a given day is fine, and is often right. Don't trade to look busy: a weak
  trade costs capital you'll want when a strong one appears. Capital left later still has value.
- Most bought options lose money. An option pays only if the stock moves MORE than the implied
  move printed in the ladder, BEFORE time decay eats it. For every option order, state your
  expected move and the reason it beats the implied move. If it doesn't clearly beat it, buy
  shares or skip.
- The best setups have a dated catalyst before your exit date (earnings, product events, macro
  prints) or a strong trend with relative strength. Avoid holding options through earnings
  unless earnings is the trade.

## Discipline
- Your training data ends before today. Every price, return and indicator must come from the
  briefing; every news fact needs a source and a date. Separate facts from your judgment.
- Read your notebook and track record first. Don't repeat mistakes you wrote down. Don't drop a
  thesis on one day's noise, and don't keep one whose invalidation level has been hit.
- Every position has a stop (underlying price), an optional target (0 = none) and an exit_by
  date. Code executes them between sessions; you can change them each session.

## Limits enforced by code (orders that break them are resized or rejected)
{limits}
"""

RESEARCH = """\
{preamble}
# Your task now: research (step 1 of 2)

Use web search for news since your last session: macro, the sectors in the briefing, every open
position and any candidate you consider. Then:

1. `position_reviews`: one entry per open position: hold or close, with the reason (has the
   thesis or invalidation changed?).
2. `candidates`: 0 to {max_candidates} names you might open today. Code will then fetch real
   option chains and quotes for exactly these names, and you'll decide in step 2. Only names
   from the scan table or liquid US large caps and ETFs (price above $5, over $50M a day traded).
   Don't list names you already hold.
3. `facts`: the news facts you rely on, each with source and date.
4. `no_trade_reason`: if you name no candidates, say why (empty string otherwise).

{briefing}
"""

DECISION = """\
{preamble}
# Your task now: decide (step 2 of 2)

Your research from step 1 and the option ladders code built for your candidates follow the
briefing. Decide:

1. `position_actions`: for every open position: hold, close, or update (new stop / target /
   exit_by; give all three, repeating unchanged values).
2. `orders`: 0 to {max_new} new positions.
   - instrument "shares": `contract` = "", `qty` in whole shares.
   - instrument "option": `contract` = a symbol copied exactly from a ladder below, `qty` in
     contracts. Code pays up to the current ask.
   - `stop` and `target` are UNDERLYING prices (calls/shares: stop below spot; puts: stop above
     spot; target 0 = none). `exit_by` = YYYY-MM-DD, before the option's expiry.
   - `expected_move_pct`: your expected underlying move by exit_by (signed). For options it must
     clearly beat the ladder's breakeven move.
   - `confidence`: 1-5, honest. It isn't used for sizing; you size with `qty`.
3. `notebook`: rewrite your notebook, at most 250 words. It is the only memory you keep between
   sessions: open theses and what would change them, lessons from closed trades, what to check
   next session. Replace stale lines instead of appending.
4. `session_summary`: at most 60 words on what you did and why.

{briefing}

# Your research (step 1)
{research}

# Option ladders and share quotes for your candidates
{ladders}
"""

_STR = {"type": "string"}
_NUM = {"type": "number"}

RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "market_view": _STR,
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fact": _STR, "source": _STR, "date": _STR},
                "required": ["fact", "source", "date"],
            },
        },
        "position_reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": _STR,
                    "action": {"type": "string", "enum": ["hold", "close"]},
                    "reason": _STR,
                },
                "required": ["id", "action", "reason"],
            },
        },
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": _STR,
                    "direction": {"type": "string", "enum": ["long", "short"]},
                    "instrument": {"type": "string", "enum": ["shares", "options", "either"]},
                    "horizon_days": {"type": "integer"},
                    "catalyst": _STR,
                    "catalyst_date": _STR,
                    "thesis": _STR,
                    "why_now": _STR,
                    "invalidation": _STR,
                },
                "required": ["ticker", "direction", "instrument", "horizon_days", "catalyst",
                             "catalyst_date", "thesis", "why_now", "invalidation"],
            },
        },
        "no_trade_reason": _STR,
    },
    "required": ["market_view", "facts", "position_reviews", "candidates", "no_trade_reason"],
}  # fmt: skip

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "position_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": _STR,
                    "action": {"type": "string", "enum": ["hold", "close", "update"]},
                    "stop": _NUM,
                    "target": _NUM,
                    "exit_by": _STR,
                    "reason": _STR,
                },
                "required": ["id", "action", "stop", "target", "exit_by", "reason"],
            },
        },
        "orders": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": _STR,
                    "instrument": {"type": "string", "enum": ["shares", "option"]},
                    "contract": _STR,
                    "qty": _NUM,
                    "stop": _NUM,
                    "target": _NUM,
                    "exit_by": _STR,
                    "expected_move_pct": _NUM,
                    "thesis": _STR,
                    "catalyst": _STR,
                    "invalidation": _STR,
                    "confidence": {"type": "integer"},
                },
                "required": ["ticker", "instrument", "contract", "qty", "stop", "target",
                             "exit_by", "expected_move_pct", "thesis", "catalyst",
                             "invalidation", "confidence"],
            },
        },
        "notebook": _STR,
        "session_summary": _STR,
    },
    "required": ["position_actions", "orders", "notebook", "session_summary"],
}  # fmt: skip


def prompt_sha() -> str:
    text = PREAMBLE + RESEARCH + DECISION + repr(RESEARCH_SCHEMA) + repr(DECISION_SCHEMA)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
