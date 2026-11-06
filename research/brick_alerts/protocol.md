# Protocol: following bricktrades' Discord option alerts

Written 2026-11-05, after counting the alerts and reading formats, **before any return
was computed**. Code: `src/horizon_trader/social/brick.py`.

## Data

- Export of the `brick-alerts` channel (Low Key Stonks Discord), 2024-12-10 to
  2026-11-05, made with DiscordChatExporter 2.48 (`data/discord/raw/`, git-ignored).
  Only messages by `bricktrades` count.
- Times come from Discord snowflake ids (set by Discord, can't be backdated). The export
  shows edits (`timestampEdited`) but only the final text. Deleted messages are missing
  (biased in his favour, size unknown).
- Stock prices: Massive day and minute files (unadjusted, split factors from
  `massive_ref`). No option prices.

## What counts as an opening alert

- A message by him with a contract (ticker, strike, call/put, expiry) **and** a price.
  Formats accepted: `TICK 60c 8/15 1.7`, `TICK 8/15 60c 1.7`, `TICK 60c 1.7 8/15`,
  `TICK 60 C 08/15/2025`, `TICK 60c next week 1.7`, `TICK 95p 1DTE 0.7`, with or without `@`,
  `$`, or `for` before the price.
- Expiry: `M/D` takes the message's year, rolled to next year if already past;
  `M/D/YY(YY)` as written; `M/YYYY` = that month's third Friday; `next week` = Friday
  of next week (weeks start Monday; posted on a weekend = the coming week's Friday);
  `this week` = this week's Friday; `NDTE` = N trading days ahead. An expiry
  on a market holiday moves to the trading day before.
- A line with no ticker takes the first ticker named earlier in the message
  (`TSLA -60% sold / Rolled to 300p 3/21 3.35`).
- Excluded: watchlist posts (a message containing "watchlist"); unusual-flow reposts
  (`TICK 18 C 03/21/2025 / Prem: $...`, which carry no price) unless the message says he
  followed it with a price (his own priced alerts in the same message still count);
  spreads (`100/120`, `spread`), covered calls, and anything sold to open.
- Parser refinements made after the first run but **before any return was printed**
  (the run crashed on a console encoding error first): the two rules above for flow
  messages and the ticker fallback, found in a sample of unparsed messages.
- The first alert of a contract is the **opening**. Later alerts of the same contract,
  and replies like `added @ 1.57` / `double down @ 0.6` matched to his latest open
  contract on that ticker, are **adds** (secondary analysis only).
- Sanity: 0 < price < stock price at the alert, and the ticker has Massive bars on the
  alert day (current listing only). Anything else is counted as untestable.

## Test 1: held to expiry (exact, no option data needed)

- Value at expiry = intrinsic value at the official close of the expiry day, in the
  alert's share basis (split-adjusted). Return R = value / his price - 1.
- Each opening contract counts once (equal premium per alert). Only expired contracts.
- Sensitivity: his price + 5% (a follower filling worse). Commissions ($0.65/contract)
  ignored.
- Reported: mean, median, % worthless, % profitable, weekly-clustered t; by call/put,
  days to expiry (<= 7, 8-30, 31-90, > 90), `HIGH RISK PLAY` tag, edited or not, and
  halves (alerts up to 2025-11-30 vs after).
- **PASS** if mean R > 0 with clustered t > 2 and mean R > 0 in both halves.
- The market's option price is the control: a buyer with no skill expects R < 0
  (the price includes the expected move plus a premium). He usually trims early, so a
  fail here doesn't by itself mean his trading loses money.

## Test 2: does he pick the stock's direction? (selection)

- Direction: +1 for calls, -1 for puts. A follower buys the stock at the open of the
  minute bar 1 minute after the alert (in session) or the next regular open
  (the existing `social.event_study` timing).
- Returns to the close 5 and 20 trading days later and to the expiry day.
- Excess: vs QQQ bought at the same moment, and **beta-adjusted**: r - beta x r_QQQ, with
  beta from 120 daily returns before the alert day (at least 60, else beta = 1).
  Signed by direction.
- **PASS** if the mean signed beta-adjusted 20-day excess > 0 with weekly-clustered t > 2
  and > 0 in both halves.
- Secondary, timing: the alert's 20-day return minus the same stock's mean 20-day
  return over all start days in the sample (does the timing add to the choice of stock?).

## Descriptive only

- His own follow-ups: replies to an opening alert with a % figure (`UPST 105% first
  trim`). Share of openings with a positive claim, and the largest claim, against the
  held-to-expiry outcome. These are self-reported and not used as returns.
- Every purchase (openings + adds), held to expiry: does averaging down help?

## Known limits

- The trades he actually makes (trims at +50-100%, stops at -40%) need option prices
  at the exit time, which we don't have. Test 1 is a fixed rule, not his P&L.
- Deleted alerts can't be counted. From now on, weekly re-exports diffed against the
  previous one will show deletions.
- 23 months, one bull market in AI and momentum names.
