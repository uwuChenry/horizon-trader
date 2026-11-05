# Shared-account results at $5k, $10k, $15k and $20k

The prior return-stream combination overstated small-account feasibility.
Actual minimum commissions, whole shares and shared buying power materially
change the result. **No allocation is established as meeting the original objective
across the required periods and adverse conditions.** These are conditional
historical account simulations, not broker-certified execution or live results.

Initial NAV 2021-11-01; first trade 2021-11-02; final mark 2026-09-24.
QQQ gross total return on the same first-open/end-close dates: **14.90%
CAGR / -35.12% maximum drawdown**. QQQ has no subscription,
transaction, withholding or financing costs; executable whole-share QQQ is a
separate saved control. Strategy figures exclude research/data subscription bills.

## Four account sizes

Frozen: 51.60% daily core / 20.33% ORB / 28.07% QQQ noise sleeve budgets.
Reduced: 100% daily core plus 25% ORB and 50% noise sleeve budgets; the intraday
strategies themselves request leverage. These weights remain unchanged at every size.

| Account | Allocation | Net CAGR | Max DD | Excess Sharpe | End NAV | Fees | Cap-breach days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| $5,000 | frozen | -11.00% | -44.47% | -2.86 | $2,826 | $3,982 | 0 |
| $5,000 | reduced | 1.09% | -15.08% | -0.23 | $5,272 | $4,353 | 3 |
| $10,000 | frozen | 3.24% | -6.49% | -0.08 | $11,691 | $4,407 | 0 |
| $10,000 | reduced | 14.16% | -8.29% | 0.93 | $19,122 | $4,729 | 6 |
| $15,000 | frozen | 7.22% | -4.90% | 0.51 | $21,103 | $4,624 | 0 |
| $15,000 | reduced | 17.71% | -8.17% | 1.19 | $33,322 | $4,940 | 16 |
| $20,000 | frozen | 8.88% | -4.64% | 0.75 | $30,331 | $4,673 | 0 |
| $20,000 | reduced | 19.53% | -8.26% | 1.32 | $47,889 | $5,080 | 16 |

Every fee minimum is charged to an executed, netted order. Positions in the same
ticker share one cash balance and one gross limit. ORB candidate orders reserve
buying power even on days they never fill. Same-time QQQ reversals are one net
order. Daily sizing uses prior-close information, with 1% reserve and resizing
after opening gaps; it is an approximate opening-session execution model.

Cap-breach days mean minute marks or closing inventory crossed the **model's**
gross limit after prices moved. They do not establish a historical IBKR margin
call. Such paths fail acceptance here; forced liquidation prices are not modeled.
The base intraday cap is 2x and the daily core's overnight cap 1x. The QQQ
volatility control has its declared 1.5x target / 2x drift limit. The account's
actual jurisdiction, house margin and small-balance restrictions remain unverified.

## Fresh 2024 account restarts

Each account starts anew at its stated size on 2023-12-29, first fill 2024-01-02.
This separates current small-balance execution from accounts grown since 2021.

| Account | Allocation | CAGR | Max DD | End NAV |
| --- | --- | --- | --- | --- |
| $5,000 | frozen | -5.07% | -17.41% | $4,336 |
| $5,000 | reduced | 9.03% | -8.30% | $6,336 |
| $10,000 | frozen | 6.06% | -5.40% | $11,749 |
| $10,000 | reduced | 19.05% | -8.52% | $16,121 |
| $15,000 | frozen | 10.06% | -4.43% | $19,500 |
| $15,000 | reduced | 23.68% | -7.95% | $26,839 |
| $20,000 | frozen | 11.71% | -4.12% | $27,081 |
| $20,000 | reduced | 24.92% | -8.21% | $36,782 |

## Costs, latency and restrictions

Full-period net CAGR below; every trial, including failures, is retained in the
[experiment ledger](results/experiment_ledger.csv). The no-minimum case is a
diagnostic added to explain fee sensitivity, not an available broker offering.
The 4x scenario is hypothetical. Long-only here means no **net account shorts**;
a short signal can first sell an existing daily long holding.

| scenario | strategy | 5000 | 10000 | 15000 | 20000 |
| --- | --- | --- | --- | --- | --- |
| daily_delay | frozen | -10.63% | 3.23% | 7.24% | 9.03% |
| daily_delay | reduced | 1.06% | 14.21% | 17.93% | 19.80% |
| delay_1m | frozen | -14.18% | -0.83% | 2.98% | 4.72% |
| delay_1m | reduced | -4.68% | 7.69% | 11.65% | 13.22% |
| delay_5m | frozen | -11.89% | 1.67% | 5.42% | 7.14% |
| delay_5m | reduced | -1.97% | 10.78% | 14.65% | 16.14% |
| higher_cost | frozen | -12.67% | 1.55% | 5.72% | 7.25% |
| higher_cost | reduced | -2.87% | 11.43% | 15.15% | 17.18% |
| hypothetical_4x | frozen | -11.00% | 3.24% | 7.22% | 8.88% |
| hypothetical_4x | reduced | 1.13% | 13.98% | 17.66% | 19.46% |
| joint | frozen | -2.91% | 1.78% | 4.20% | 5.09% |
| joint | reduced | -0.51% | 6.18% | 8.61% | 9.67% |
| missed_orb | frozen | -9.19% | 3.13% | 6.62% | 8.10% |
| missed_orb | reduced | 1.97% | 13.57% | 16.74% | 18.61% |
| no_minimum_diagnostic | frozen | 11.17% | 12.08% | 12.16% | 12.69% |
| no_minimum_diagnostic | reduced | 21.64% | 22.56% | 22.40% | 22.61% |
| no_shorts | frozen | -2.92% | 2.52% | 5.05% | 6.20% |
| no_shorts | reduced | 2.77% | 9.80% | 12.70% | 13.94% |
| tiered | frozen | 4.81% | 9.26% | 10.75% | 11.61% |
| tiered | reduced | 15.35% | 19.61% | 20.84% | 21.47% |
| unlevered_long_only | frozen | -2.93% | 2.44% | 4.96% | 6.04% |
| unlevered_long_only | reduced | 0.34% | 7.44% | 10.13% | 11.09% |
| withholding_30pct | frozen | -11.05% | 3.17% | 7.10% | 8.80% |
| withholding_30pct | reduced | 0.90% | 13.69% | 17.40% | 19.34% |

Latency replays the same ORB candidate with later order placement, requires a
trigger and later-minute trade-through, then computes a new stop path. Noise
signals fill one/five minutes later. Higher-cost cases add 1c on all intraday fills,
including auction exits, and use 10bp for daily fills. Joint stress also adds one
daily-session delay, 1x/no-net-shorts, deterministic missed ORB entries and 30%
dividend withholding. Borrow is an assumed 3% annualized on the day's peak net
short value, charged for a full day; no historical locate availability is implied.
Paired 21-session block-bootstrap intervals for incremental Sharpe are saved in
[uncertainty.csv](results/uncertainty.csv). They do not correct prior strategy selection.

## Older-regime validation

Existing-subscription checks returned **HTTP 403** for 2017-01-03 and 2020-03-16
minute files. No purchase or subscription change occurred. The following extension
uses existing daily ETF histories, 2007-01-03 initial NAV through 2021-10-01.
It covers daily controls only; older ORB/noise/combined validation remains unfinished
pending data access. Financial crisis, pre-COVID and COVID subperiods are saved.

| Account | Control | CAGR | Max DD |
| --- | --- | --- | --- |
| $5,000 | core | 4.46% | -10.91% |
| $5,000 | qqq_buy_hold | 15.66% | -52.69% |
| $5,000 | qqq_vol_only | 15.48% | -38.41% |
| $10,000 | core | 5.65% | -10.88% |
| $10,000 | qqq_buy_hold | 15.66% | -52.69% |
| $10,000 | qqq_vol_only | 15.75% | -38.79% |
| $15,000 | core | 5.86% | -11.16% |
| $15,000 | qqq_buy_hold | 15.68% | -52.81% |
| $15,000 | qqq_vol_only | 15.91% | -38.69% |
| $20,000 | core | 5.93% | -11.24% |
| $20,000 | qqq_buy_hold | 15.67% | -52.78% |
| $20,000 | qqq_vol_only | 15.97% | -38.62% |

## Forward observations

The read-only observer successfully connected to the paper Gateway. Recorded
event counts: `{"account": 7, "api_error": 10, "connected": 1, "connection_failed": 2, "end": 1, "heartbeat": 1, "start": 3, "subscriptions": 1}`. Valid two-sided live-type quote
rows: **0**. Actual recorded broker execution events/snapshots:
**0**
(may include duplicate snapshot/event records). It does not submit orders.

Windows task `horizon-trader observations` is registered for weekdays at 09:24 ET,
refreshes recent Massive history and observes until 16:05 ET. Gateway must remain
logged into paper and the PC available. Scanner and ORB intent logs include all
four starting sizes. These are unsubmitted candidate intents, not funded forward
portfolio returns. Commission/execution events are captured if paper orders are
placed through the existing adapter or manually; none were placed by this work.
The first check received IBKR error 354 for every ETF; live-to-paper sharing is
being configured. Subscription errors, delayed types and missing quotes remain
explicit in logs. [IBKR sharing instructions](https://www.ibkrguides.com/clientportal/papertradingaccount.htm).

## Reproducibility and limitations

Verification: **188 account paths**, 1294
source hashes; maximum independent daily-cash reconstruction error
2.31e-11 dollars. Whole-share orders, finite NAV
and per-order fee amounts checked. The full repository test result is recorded in
the final verification note. Protocol, raw actions, prices and signals are frozen;
large/private artifacts stay in `data/shared_account_2026_10_01/` (git-ignored).
Preserve that directory along with the report for exact replay.

This model still uses inherited ORB fill assumptions without quote/queue history,
minute-resolution rather than tick-level margin, gross-dividend baseline, zero
cash interest, a dividend-payment proxy where vendor dates are absent, approximate
opening executions and uniform historical fee schedules. No historical short
availability or account restrictions were invented. Reused history is not an
untouched holdout. The existing live strategies/settings were not changed.

[Offline capital curves](capital_comparison.html),
[account checks](results/account_verification.csv),
[implementation decisions](implementation_notes.md), [frozen protocol](protocol.md).

```powershell
.venv/Scripts/python.exe research/shared_account/prepare.py raw
.venv/Scripts/python.exe research/shared_account/prepare.py dividends
.venv/Scripts/python.exe research/shared_account/prepare.py minutes
.venv/Scripts/python.exe research/shared_account/replay.py --stage main
.venv/Scripts/python.exe research/shared_account/replay.py --stage stress
.venv/Scripts/python.exe research/shared_account/replay.py --stage older
.venv/Scripts/python.exe research/shared_account/report.py
```
