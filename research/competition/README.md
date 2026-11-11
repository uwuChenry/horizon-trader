# Investment club competition: October 7 to December 31, 2026

Status: proposed competition plan, based on the owner's confirmed rules. No
competition trades, broker resets, account changes, or strategy deployments have
been made. The allocations and decision rules below are design choices, not
backtest results or an established optimal strategy.

## Confirmed mandate

- Starting simulated capital: USD 5,000; start October 7, 2026.
- End date: December 31, 2026; exact scoring cutoff/time zone remains unconfirmed.
- Score: highest realized profit; ALL positions must be closed by December 31.
  Treatment of commissions, financing and futures variation margin needs clarification.
- Objective: maximize probability of finishing first; a complete simulated loss
  is acceptable. This differs from maximizing expected wealth or long-run growth.
- Products: stocks, ETFs, options, and futures permitted in principle, subject
  to ordinary IBKR margin and actual account permissions. IBKR Pro Tiered.
- Monitoring: less than 30 minutes per US trading day; favor scheduled swings.
- Approximately 30 other competitors, or 31 entrants including the owner.
  Opponents' positions and holdings are hidden. Visibility of profit-only standings
  is unconfirmed; do not assume access to a live leaderboard. No numerical
  probability of winning can be established without a model of competing
  portfolios and uncertain future returns.

For planning, count realized gains AND losses and charge all costs. Closing every
position before the deadline is a confirmed competition requirement. Maintain net
liquidation equity alongside the official score throughout the competition.

## Proposed approach

Use concentrated stock swings plus a limited budget for large directional option
payoffs. Screen the semiconductor/memory thesis alongside other liquid leaders;
MU, TSM, AMD, NVDA and SMH are research candidates, not current buy instructions.
SOXX and QQQ provide controls. Several semiconductor positions are one correlated
economic bet; count their stock and option exposures together.

Intraday ORB is an optional future branch only if unattended execution and
monitoring are established. It is not part of the initial plan given the time
constraint. Futures are conditional on actual overnight margin, contract size,
scenario loss, and remaining buying power; no assumed retail intraday margin.

### Initial capital envelope

| Use | Starting budget | Proposed implementation |
|---|---:|---|
| Concentrated stock/ETF swings | Up to $3,000 | Two or three liquid positions, held days to weeks |
| Directional options | Up to $1,500 premium/debit | Two $750 or three $500 ideas, only if executable contracts fit |
| Uncommitted cash | At least $500 initially | Fees, flexibility, and later opportunities |

This is an unborrowed starting layout; options already add economic leverage.
Unused budgets stay in cash. Do not select a remote strike just to make a ticket
fit. If an acceptable call is too expensive, compare a vertical debit spread,
stock shares, or no trade. Do not assume fractional option contracts. Verify the
actual multiplier and deliverable, particularly after splits or other actions.

The $1,500 is an initial gross premium-spending allowance, not an instruction to
refill the bucket after every loss. Additional spending requires an explicit
dated allocation decision based on current equity, remaining time and standings.
Record premium spent, proceeds, realized losses and remaining open value separately.

For stock swings, start with a planned exit loss around $150-$250 per independent
idea. Size by both position value and distance to the thesis-invalidating exit;
whole-share rounding can materially change the position. Stops do not cap gap
losses. Option tickets are sized assuming the entire debit can be lost, without
relying on an option stop to establish maximum loss.

Accepting a possible wipeout does not require spending everything immediately.
Remaining capital has value because new opportunities and leaderboard information
arrive before December. The appropriate escalation depends on those observations.

## Choosing and managing a trade

Before entry, record a dated trade card with:

1. Public-information thesis, source timestamps and what the market may be
   underestimating. Separate facts, management forecasts and our judgment.
2. A catalyst or expected development before December 31. A 2028 supply thesis
   alone does not determine the payoff in this competition.
3. Price behavior relative to the sector and QQQ, entry condition and maximum
   acceptable entry price. Define any breakout using prior sessions, not a
   future high. An unfilled limit order is a missed trade, not an invented fill.
4. Instrument comparison: shares versus long call/put versus debit spread,
   using synchronized bid/ask quotes, actual expiries, multiplier and fees.
5. Bear/base/bull closing values on the planned EXIT DATE, including time decay
   and implied-volatility changes. Do not substitute expiry payoff for the
   value of a January option sold in December. Scenario probabilities are
   uncertain judgments, not broker-implied guarantees.
6. Whole-share/contract quantity, debit or financing, overnight initial and
   maintenance margin, excess liquidity, and combined exposure with existing bets.
7. Thesis invalidation, scheduled review, event policy and latest exit date.

Concentration is intentional, but ticker count is not diversification. A stock
position and calls on the same issuer share the same thesis. Semiconductors and
Nasdaq futures also overlap substantially. Stress the combined portfolio rather
than independently adding attractive standalone backtests.

Default option research compares contracts with enough time for the catalyst,
often 45-120 days remaining, including January 2027 expiries for a December exit.
This range is a candidate convention, not a proven optimum. Compare outright calls
when retaining a very large upside matters; compare debit spreads when option
prices are high and a capped target could still meet the competition objective.
A spread's maximum profit must be large enough to help close the leaderboard gap.

No initial naked option selling, same-day-expiry program, or daily scalping engine
is proposed: their execution demands and payoff structures are poor matches for
this specific $5,000, low-monitoring, first-place objective. Short market views can
instead be expressed with appropriately sized long puts or debit put spreads.

Manage multi-leg trades as combinations. Close or roll before expiration-related
exercise/assignment can create an unaffordable stock position; early assignment
of an American-style short leg remains possible. Check dividends and corporate
actions at each review. A defined expiry payoff does not eliminate operational risk.

For a material earnings announcement, explicitly choose beforehand between keeping
the position, reducing it, or entering after results. A default preference for
post-announcement confirmation is an untested design choice. A pre-announcement
trade needs an explicit price-move and volatility case; strong earnings alone do
not establish an attractive long-option trade.

## What the starting layout could do

Arithmetic scenarios only; no probabilities, forecast, fees or financing included.
Option multiples mean liquidation proceeds divided by original premium. A 5x
value is a 400% profit on the option, not a 500% profit. The 5x row is not attainable
for a debit spread whose contractual maximum value is below five times its debit.

| Stocks | Options' closing value | Ending account | Account return |
|---|---:|---:|---:|
| -20% | 0x cost | $2,900 | -42% |
| Flat | 0.5x cost | $4,250 | -15% |
| +20% | 2x cost | $7,100 | +42% |
| +20% | 5x cost | $11,600 | +132% |

These are selected examples, not bounds. Stocks can fall further, repeated losses
can consume the account, and leveraged positions can be liquidated before equity
reaches zero. The initial budget is deliberately high variance without requiring
full account exposure to one expiring option.

## Tournament decisions

If profit-only standings are available, review them weekly and after a major
realized result. If unavailable, use the fixed initial policy with dated reviews
of opportunity quality and remaining time; do not escalate on an imagined leader
or assume rivals own semiconductors. Let E be our equity
after allowing for closing costs, and L the comparable leader equity/score converted
to equity. L/E - 1 is the gain needed merely to catch today's leader; competitors
can continue gaining. Example: $5,000 versus $7,500 requires +50%, not +25%.

- Early phase: deploy only qualifying ideas; preserve capacity for later decisions.
- Contending: keep the strongest thesis exposure; do not add trades to appear busy.
- Leading late: reduce the chance of surrendering the lead. Cash can help, but the
  optimal hedge depends on rivals' exposure and the size of the lead.
- Far behind late: consider a larger, explicitly budgeted convex position if its
  plausible payoff can close the gap. A capped spread may be insufficient.
  Compare the chance of catching the field across actual quotes; do not equate
  the cheapest option or greatest volatility with the greatest chance of winning.
- A loss by itself never triggers an automatic doubling rule. Reassess opportunity,
  field position and remaining capital together.

The field has about 31 entrants, but its strategy mix and return distribution are
unknown. Retain these conditional branches rather than inventing a winning return
target. Evaluate candidate policies against several hypothetical opponent mixes
if performing tournament simulations; those outputs are model-dependent, not
empirical win probabilities. Each major allocation change gets a dated rationale.
Do not retroactively edit the original trade thesis.

## Daily workload and final scoring

- About 5 minutes before the session: events, material news, alerts, margin status.
- About 15 minutes in the final half-hour of regular trading: review positions,
  compare quotes, place or adjust a small number of planned limit/combination orders.
- About 5 minutes afterward: save fills, commissions, financing, realized P&L,
  unrealized P&L, equity, remaining premium budget and upcoming actions.
- Weekly review replaces one daily research block: standings, thesis updates,
  exposure and cash allocation. No obligation to trade every day.

Identify holdings needing earlier exits during December 28-30. Complete sales and
buybacks before the organizer's December 31 cutoff, leaving time for partial fills
and instrument-specific hours. Cancel open entry orders and reconcile the final
statement; do not assume selling at the last second will fill. All positions must
be closed; the exact cutoff time remains pending organizer clarification.

## Existing repository evidence and limitations

- [Stock momentum](../winners_momentum/README.md): the point-in-time top-10 study reported
  45.4% annualized net return, a roughly 40% drawdown and a 27% loss in July 2026.
  It uses fractional sizing and a short, favorable 2022-2026 sample. It does not
  validate concentrated stock picks, options, or a particular three-month return.
- [ORB follow-up](../orb_ema/exit15_tiered1c/README.md): the stop-or-close
  baseline outperformed the EMA exits under stated Tiered/1-cent assumptions.
  Costs, live fills and monitoring remain material; intraday is not the initial plan.
- [Shared account study](../shared_account/README.md): costs, whole shares
  and common buying power changed results substantially. No allocation established
  its original objective across required periods and stresses.
- [QQQ research cycle](../qqq_research_cycle/README.md): no candidate met that cycle's
  combined return/drawdown objective. Its conservative objective differs from this
  contest; rejected results must not be relabeled successful tournament evidence.
- [Derivative data review](../portfolio_data_review/vendor_futures_options.md):
  data requirements were researched; this is not a validated options/futures strategy.
- The current broker adapter constructs stock contracts. Its existing paper-only
  guard does not establish derivatives support. The ledger documentation describes
  virtual $5,000 budgets over a historically $1 million paper account; current
  account state has not been checked in this planning task. A virtual ledger alone
  cannot enforce the broker margin of a true $5,000 account.

## Setup and research sequence

1. Confirm remaining scoring details and deadline time; preserve the
   official starting statement. Establish a dedicated competition ledger and actual
   $5,000 paper buying power before relying on any margin preview. Coordinate any
   reset with existing paper activity; no reset is performed by this document.
2. Verify the actual commission schedule, product permissions, live options/futures
   data, residence-specific margin and same-day trading restrictions. The old repo
   recorded a Fixed quote despite an intended Tiered plan; user now specifies Tiered.
3. Refresh a small liquid watchlist and compare two or three thesis candidates using
   current executable quotes. Obtain actual option chains; no strike, expiry or entry
   price has been selected or certified affordable in this plan.
4. Reuse stock momentum as a control. Evaluate a small preregistered set of concentrated
   alternatives against cash, QQQ, SMH and SOXX over comparable roughly three-month
   windows. Include actual $5,000 whole-unit sizing, costs, joint exposures and margin.
   Report terminal-wealth distributions and liquidation frequency, not CAGR alone.
5. Acknowledge historical reuse: overlapping windows are dependent and earlier repo
   experiments consumed much of the recent history. No new untouched holdout is
   created by changing the objective. Option scenario models are not historical
   option backtests without archived chains, expiries and bid/ask data.
6. Prepare timestamped trade cards and a scenario/exposure view. Add ongoing realized
   P&L and leaderboard tracking to the dashboard only when implementing the plan.
   Begin with manually reviewed simulated orders; automation requires separate
   derivatives handling, reconciliation and operational validation.

## AI contest trader (built 2026-11-11, replaces the follower below)

The follower never traded: the journal said "no new trade" on all four days from 2026-11-05 to
2026-11-10 (its protocol makes that the normal answer), so the account sat at $5,000.00 with no
fills. Owner's decision (2026-11-11): the AI entry decides for itself. **Fully discretionary**
(any liquid US stock/ETF, long shares or long calls/puts), **no activity mandate** (the prompt
says flat is allowed but explains why cash never wins a winner-take-all contest), swings and
options first, intraday (ORB pick, QQQ noise) in phase 2. Model: `gpt-6-astra` at high reasoning
effort through `codex exec`. The journal is untouched and stays a separate pre-registered test;
its latest view is shown to the trader as one input.

`agents/contest_trader.py` (prompts in `agents/contest_prompts.py`), one session a weekday at
13:30 ET (`ops.jobs contest`) plus a sync in the 18:00 evening job:

1. Code builds a briefing: account, positions with live marks, the track record of closed
   positions, last session's rejected orders, the model's own **notebook** (its only memory,
   rewritten every session, at most 250 words) and last 5 session summaries, the journal's
   market packet and latest view, and a scan table of ~70 liquid names (returns, RSI(2)/RSI(14),
   distance to moving averages and highs, ATR, dollar volume).
2. **Research call** (web search on): news, a hold/close review of each position, 0-4 candidates.
3. Code builds **option ladders** for exactly those candidates from real chains (live IBKR
   bid/ask first): 3 expiries (~14/35/63 days), ATM to ~15% OTM, only contracts with open
   interest >= 100 and a spread <= 25% of mid, each with breakeven, move to breakeven and the
   expiry's ATM implied move.
4. **Decision call** (no tools): position actions, orders that must name a ladder contract (so
   no invented strikes or prices), an expected move that must beat the breakeven move, a new
   notebook and a session summary.
5. **Code checks** resize or reject every order; rejections are shown in the next briefing.

| Rule (code) | Value |
|---|---|
| Positions | at most 6, one per underlying, at most 3 new per session |
| Shares | at most 40% of equity per position, 100% in total (no margin), whole shares, stop at most 15% below the entry as a **GTC stop at Alpaca** |
| Options | long calls/puts only, at most 20% of equity premium per position, 50% in total; the underlying stop/target are checked once per session (not instant) |
| Liquidity | stock above $5 and over $50M a day; IEX spread <= 1% |
| Exits by code | stop/target, the model's `exit_by`, option expiry eve, everything from 2026-12-28; no new positions after 2026-12-23 |
| Guards | paper keys only, kill switch `data/live/KILL`, the account pinned on 2026-11-05 (`PA31SWJZFFPD`), positions must reconcile |

Records: `data/live/competition_ai_paper/` (same ledger as the follower: equity.csv, fills.csv,
state.json; `trader.json` holds positions, notebook and session summaries;
`sessions/<date>_<HHMM>/` holds the briefing, both prompts and raw answers, the ladders, the
check results and the summary). About 7 weeks of one model on simulated paper fills says nothing
about skill: this is a contest entry and a harness test, reported as such.

## AI competition account on Alpaca (built 2026-11-05, retired 2026-11-11)

Owner's decision (2026-11-05): the AI entry follows the forecast journal
([research/forecast_journal](../forecast_journal/README.md)) instead of getting its own trader,
first at 2.5x the journal's sizing, then (same day, before any trade) in a high-risk
contest mode: the owner's view is that only large, convex bets can win a short
winner-take-all contest, and a simulated wipeout is accepted. `agents/competition.py` executes; the journal decides and stays
untouched, so its pre-registered test (prompts, rules, mirrors) is unchanged. The journal's
protocol only sends ideas to Alpaca after an ideas PASS at 60+ days, which falls after
December 31; this account is therefore a **separate experiment** and is reported separately,
not as evidence for or against the journal.

| Rule | Value |
|---|---|
| What is traded | Journal ideas only, never the mirrors; opened only on the idea's decision date |
| Option sizing | **High-risk contest mode (owner, 2026-11-05):** $1,000 debit per idea, $4,000 open in total (journal: $150 / $600) |
| Shares sizing | $2,000 per idea, $4,000 open in total, fractional shares; cash limits options + shares together |
| Shape | A debit-spread idea buys **only its long leg** (a capped payoff can't win a winner-take-all contest); ideas with confidence 1-2 get half the budget |
| Entry | Day limit order at the current ask (spreads: one multi-leg order at the net debit); unfilled = missed, never retried |
| Exit | Market orders, short leg first: when the journal closes, one trading day before expiry (no exercise or assignment), and everything from 2026-12-28 |
| No new ideas | after 2026-12-23, or after 15:57 ET |
| Guards | paper keys only, kill switch (`data/live/KILL`), same account as the first run, first run needs $1k-$10k equity, positions must reconcile, no new orders while one of ours is working |

Quotes: live IBKR option quotes first (Gateway, read-only, client id 32), used only when
IBKR has every leg of an idea; otherwise Alpaca's free indicative feed for all legs. Each
record stores `quote_source`. Stock limits use Alpaca's IEX quote.

Records: `data/live/competition_ai_paper/` (equity, fills with Alpaca's price next to the
journal's modeled price, `follow.json` with every idea's status and reason). Limits: paper fills are simulated, so the fill
comparison is an execution check, not a measurement of live costs. The journal sizes for a $10k
hypothetical account, so the 2.5x scaling is a sizing choice, not something the journal tested.

## Official references checked October 7, 2026

- [IBKR paper account behavior and limitations](https://www.ibkrguides.com/advisorportal/aboutpapertradingaccount.htm):
  paper permissions/data mirror the linked account; fills use top-of-book data,
  combination support is limited and stop behavior can differ from production.
- [IBKR stock commissions](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php)
  and [margin requirements](https://www.interactivebrokers.com/en/trading/margin-requirements.php):
  Tiered pricing is a fee schedule, not a grant of unrestricted leverage.
- [OIC long calls](https://www.optionseducation.org/strategies/all-strategies/long-call):
  premium can be lost, and time and volatility affect pre-expiry value.
- [OIC debit call spreads](https://www.optionseducation.org/strategies/all-strategies/bull-call-spread-debit-call-spread):
  expiry profit is capped by strike width less debit, adjusted for multiplier and fees.
- [CME Micro E-mini Nasdaq specifications](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html):
  MNQ is $2 per index point. Contract margin is collateral, not maximum loss.
- [SEC investor bulletin on intraday margin transition](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/margin):
  broker transition timing matters; do not assume uniform same-day trading access.
