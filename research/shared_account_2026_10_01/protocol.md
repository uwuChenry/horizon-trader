# Shared account and capital sensitivity — frozen protocol

Requested: one funded account at $5,000, $10,000, $15,000 and $20,000;
forward execution observations; additional validation. Written before replay.

Signals remain the existing configured daily ETF book, baseline top-one 5-minute
ORB / 1 ATR / stop-limit entry, and the existing QQQ noise-area strategy.
Use the previous review's exact frozen allocation weights (0.515977585263584,
0.20332137002741696, 0.2807010447089991) and its reduced overlay (1, .25, .5).
No allocation or signal parameter search and no selection of the best capital size.

Controls: daily core, ORB, noise alone; delete each sleeve from the reduced overlay;
QQQ gross total return, executable whole-share QQQ, and volatility-managed QQQ.
Primary period: initial NAV 2021-11-01, returns 2021-11-02 through 2026-09-24,
matching the previous review. 2021–23 is development/reused history, 2024+ reused
confirmation, 2022 a separate stress. Additional available September sessions are
reported separately and cannot establish an edge. Fresh 2024 $5k/$10k/$15k/$20k
restarts distinguish capital effects from accounts grown since 2021.

Accounting: raw shares, integer orders, one cash balance, net same-symbol orders
at the same event, actual per-order fee minimums from the repository Fixed model.
Daily decisions use prior closes and execute next open with a 1% sizing reserve.
Intraday desired sizes use starting-day account equity and frozen sleeve budgets.
Each event marks every holding with then-available prices; post-cost buying power
is reserved sequentially, reducing/rejecting orders when needed. Reversals are one
net order. No separate capital or cash interest is credited to intraday sleeves.
Splits adjust share quantities; dividends become receivables on ex-date and cash
on known pay date, or a disclosed conservative 45-calendar-day proxy when absent.
Receivables enter NAV but cannot fund purchases. Gross dividends, withholding stress.
Funding on actual overnight cash debit, lagged DFF + 150bp; short exposure charged
an assumed 3% annualized for at least a day (not a historical locate/borrow quote).

Primary cap: 2x net account gross intraday, 1x overnight. These are MODEL limits,
not a certification of IBKR house margin, account type, jurisdiction or short
availability. Additional 1x/no-net-shorts and hypothetical 4x cases are mandatory.
Missed fills do not free capital before cancellation; the replay's synchronous
event model assumes acknowledgement before the next order and no working orders.
Flag any intervening mark breach; no result with a breach qualifies for promotion.
Minute/event marks do not establish worst-tick intraday losses or auction liquidity.

Stress existing blend rules at every size: Tiered pricing, higher costs (daily
10bp, intraday +1c including auction exits), one-/five-minute signal delays,
one extra daily session delay, no net shorts, deterministic missed ORB entries,
and a joint adverse case. ORB latency must resimulate entry and stop after delay;
never reuse an old exit that precedes a delayed entry. Do not silently treat a
saved filled-trade list as all candidate/order decisions.

Acceptance: higher net CAGR than QQQ and maximum drawdown magnitude <=90% of QQQ
on identical dates, in full/reused confirmation and joint adverse stress, with no
account-limit breaches. Costs, order/rejection counts, dividend/funding flows,
capacity clipping and all failures are retained. No claim of untouched holdout.

Validation extension: probe existing older-data entitlement without purchases;
if unavailable, record the precise access outcome, test daily controls in older
regimes using existing daily history, and retain full intraday validation as a
data dependency. Never synthesize missing intraday regimes from daily bars.

Forward evidence: read-only paper-account observer, timestamped scanner/quotes/
orders/status/cancellations/executions/commissions, explicit missing/delayed data.
No live orders. Record current observations and prepare a weekday collector;
future fills cannot be claimed before they occur. Preserve existing ledgers.
