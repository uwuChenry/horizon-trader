# Two-close EMA confirmation, narrower stops and sizing

Requested after the exit diagnostics; executed 2026-10-03 on the same frozen
history ending 2026-10-01. Rules and comparisons fixed before running this experiment.

- Interpret "0.5R stop" as **half the original 1-daily-ATR price distance**, i.e.
  **0.5 daily ATR**. This is distinct from a 0.5% equity risk budget. Once a new
  stop is chosen, that stop defines the new 1R for the trade. The owner explicitly
  confirmed the 0.5-daily-ATR interpretation before results were run.
- Keep original ORB entries only: same 1,001 triggered trades on 1,240 sessions,
  top-one stock, opening-candle direction, five-minute range, same entry prices.
  No new stock filters, entry cutoffs, targets, reentries or overnight positions.
- Compare three exits: (1) original fixed stop or closing auction; (2) one adverse
  completed 15-minute EMA(12) close; (3) **two consecutive adverse completed
  15-minute EMA(12) closes**. The new confirmation counter starts after entry.
  A favorable close, equality, or missing intervening 15-minute candle resets it.
  Entry-time signals cannot count retroactively. Once confirmed, exit at the
  next available minute open. The initial protective stop stays active throughout.
- Stops: **1.0 and 0.5 prior daily ATR**, each anchored to the raw entry price.
  Risk budgets: **1% and 2%** of start-of-day equity. Notional sizing limits:
  **2x and 4x equity**, independent of risk budget. Shares are
  `floor(min(equity * risk / stop_distance, equity * cap / entry_fill))`.
  Raising the cap does not force additional exposure if the risk budget binds.
- This gives six price paths per date and **24 exit/stop/risk/cap combinations**.
  Show all combinations at Tiered + **1c/share** entry/non-auction-exit slippage,
  plus a zero-cost diagnostic. Each full/subperiod run starts with **$5,000**.
  Preserve all flat sessions and independent 2021-23 / 2024+ account restarts.
- Main comparison: one-close vs two-close at **1 ATR, 1% risk, 2x cap**. Secondary:
  narrower stops at fixed risk; higher risk at fixed stop; higher cap at fixed
  stop/risk. Do not select a favorable configuration after seeing the table.
- Report CAGR, close-to-close drawdown, zero-hurdle Sharpe, net win rate, stop
  rate, mean/worst trade return, mean/median/p95/max entry notional/equity, nominal
  stop risk actually deployed, and fraction constrained by the notional ceiling.
  Count prior 1-ATR winners stopped out by the 0.5-ATR version using identical
  baseline share counts to isolate price-path changes from compounded sizing.
- Recompute the original and one-close paths and assert exact agreement with the
  saved experiment before interpreting the new exit. Hash sources and preserve
  the earlier artifacts. Record every new result, including failures.

Leverage scenarios are **research assumptions, not verified broker buying power**.
IBKR says house margin may exceed standard requirements; see its
[margin documentation](https://www.interactivebrokers.com/en/trading/margin-requirements.php).
No borrow/locate costs, dynamic house margin or forced liquidation are modeled.
Drawdowns are daily closing-equity drawdowns, not intraday peak-to-trough losses.
Slippage/gaps can exceed the nominal stop risk; the
[SEC stop-order bulletin](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-15)
explains that a stop price does not guarantee an execution price. No live or paper
orders, account setting changes, or automatic adoption follow from this study.
