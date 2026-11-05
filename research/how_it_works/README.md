# How the system works: the daily book, QQQ noise, and execution

Plain-language reference for what each strategy does, how its orders are decided, and what is
(and isn't) automated yet. Written 2026-09-25 from the code; file paths are given so each
rule can be checked. Results are summarized here; the full evidence is in the other notes.

## The big picture

```
prices ──> sleeves (each says "what I'd like to hold") ──> portfolio (scale, net, cap)
       ──> orders (only the difference from what we hold) ──> broker
```

- **A sleeve** is one strategy. It never places orders; it only outputs **target weights**,
  e.g. "30% SPY, 20% GLD".
- **The portfolio layer** combines the sleeves into one list of targets.
- **Execution** compares the targets with current holdings and trades only the difference.

The same code produces the backtest and the live targets, so what's tested is what would trade.

Two kinds of strategy run on top of this:

| | Daily book | Intraday sleeves (ORB, QQQ noise) |
|---|---|---|
| Decides | Once a day, after the close | During the trading day |
| Holds | Days to months | Minutes to hours; **always flat by the close** |
| Trades | A few times a month | Up to once or several times a day |
| Status | Backtested; daily targets computed (`run_daily --dry-run`) | Backtested only |

## Part 1: the daily book

Four sleeves, each given a fixed share of the account (`config/settings.yaml`). The shares
were set in advance, not optimized:

| Sleeve | Share of account | Horizon | Idea in one line |
|---|---|---|---|
| Momentum rotation | 30% | Months | Hold the 3 strongest asset classes of the past year |
| Trend following | 25% | Months | Hold every asset class that's in an uptrend, sized by risk |
| Volatility-managed SPY | 20% | Weeks–months | Hold less SPY when the market is turbulent |
| Mean reversion (RSI(2)) | 15% | Days | Buy short, sharp dips in index ETFs that are in uptrends |
| *(cash, reserved for a future LLM sleeve)* | 10% | | |

**The universe:** 10 liquid ETFs covering US stocks (SPY, QQQ, IWM), international (EFA),
emerging markets (EEM), real estate (VNQ), commodities (DBC), Treasuries (TLT, IEF) and gold
(GLD).

### Momentum rotation (`sleeves/momentum.py`)

1. On the **first trading day of each month**, measure each ETF's return from 12 months ago to
   1 month ago. Skipping the latest month is standard: very recent winners tend to reverse
   briefly (Jegadeesh & Titman).
2. An ETF is **eligible** only if that return is positive **and** its price is above its
   200-day average (an "absolute momentum" filter, as in Antonacci and Faber).
3. Hold the **top 3 eligible ETFs, a third each**. If fewer than 3 qualify, the empty slots
   stay in cash. That's what cuts drawdowns in bear markets: when most assets are falling,
   few qualify.
4. Hold until the next month's rebalance.

### Trend following (`sleeves/trend.py`)

Time-series momentum (Moskowitz, Ooi & Pedersen 2012), long-only:

1. Monthly, each ETF is "in trend" if its 12-month return is positive.
2. Each ETF gets a **risk budget proportional to 1 / its volatility** (63-day), computed across
   all 10, so calmer assets such as Treasuries get more weight than volatile ones such as
   emerging markets.
3. ETFs not in trend leave their budget **in cash**; it's not handed to the others.

This sleeve overlaps heavily with momentum (correlation 0.85), which is why merging or cutting it
is an open decision.

### Volatility-managed SPY (`sleeves/vol_managed.py`)

Moreira & Muir (2017):

1. Monthly, measure SPY's realized volatility over the last 21 trading days.
2. Weight = (15% target volatility)² / (realized volatility)², capped at 100% (no leverage).
3. **Example:** if SPY's recent volatility is 15%, hold 100%. If it jumps to 30%, hold
   (0.15/0.30)² = 25%. Calm markets mean fully invested; turbulent markets mean mostly cash.

The idea: when volatility spikes, returns per unit of risk tend to be worst, so owning less
then improves the risk-adjusted result. This was the most robust sleeve in testing.

### Mean reversion, RSI(2) (`sleeves/mean_reversion.py`)

Connors-style dip buying on SPY, QQQ and IWM, checked **every day**:

1. **RSI(2)** measures how stretched the last two days' moves are, from 0 (heavily sold) to 100.
2. **Buy** when RSI(2) < 10 **and** the price is above its 200-day average (a dip in an uptrend).
3. **Sell** when RSI(2) > 70, **or** the price falls below the 200-day average, **or** after 10
   days (a time stop).
4. At most 3 positions, a third of the sleeve each; if more qualify, the most oversold win.

The weakest sleeve (Sharpe 0.49), kept because it's the least correlated with the others.

### From four sleeves to one set of orders (`portfolio/`, `execution/rebalance.py`)

1. **Scale:** each sleeve's weights × its share of the account. For example, momentum holding
   SPY at 1/3 contributes 0.30 × 1/3 = **10% of the account in SPY**.
2. **Net:** add up the same ticker across sleeves. If momentum wants 10% SPY and vol-managed
   wants 20%, the target is 30%.
3. **Cap:** no ticker above 60% of the account; total holdings at most 100% (no leverage).
4. **Compare with holdings** and create orders for the differences, with three rules that
   stop a small account bleeding commissions:
   - **Rebalance band:** an existing position is only resized once it's more than 2% of equity
     away from its target. Opening or fully closing a position always goes through.
   - **Dust filter:** orders under $25 are skipped.
   - **Sells before buys,** so sales free up cash for purchases.
   - Fractional shares are allowed (IBKR supports them).

### Timing and costs (backtest, `backtest/sim.py`)

- **Targets are decided from the close of day t and traded at the open of day t+1.** A signal
  can never trade on the price that produced it.
- Fills at the open price ± 5 basis points of slippage, plus IBKR Pro Tiered costs ($0.0035/share,
  $0.35 minimum, clearing, an assumed exchange fee, SEC/FINRA fees on sells).

### How it has done (2008–2026, $5k, IBKR Tiered)

| | CAGR | Sharpe | Max drawdown |
|---|---|---|---|
| **Combined daily book** | 6.5% | 0.83 | −12% |
| Momentum rotation alone | 9.9% | 0.76 | −18% |
| Vol-managed SPY alone | 9.7% | 0.81 | −21% |
| Trend following alone | 5.0% | 0.73 | −14% |
| Mean reversion alone | 2.7% | 0.49 | −19% |
| SPY buy & hold | 11.3% | 0.64 | −52% |

The combined book earns less than SPY but with about a quarter of SPY's worst drawdown. Over
Nov 2021 – Sep 2026 it returned 7.3% a year at a Sharpe of 0.91.

## Part 2: QQQ noise-area momentum

Replicated by the other agent in `intraday/market_momentum.py` from Zarattini, Aziz & Barbon
(2024), *Beat the Market*. The paper tests SPY; it failed there after publication, but held
up on QQQ.

**The idea:** most intraday movement is noise. Only when QQQ moves further from the open than
it usually does by that time of day is there real one-sided pressure, and that tends to
continue for the rest of the day.

**The rules** (all at the paper's defaults, nothing tuned):

1. **The noise band.** For every minute of the day, take the average absolute move from the
   open at that minute over the previous 14 days. Call it σ (it grows through the day).
   - Upper band = max(today's open, yesterday's close) × (1 + σ)
   - Lower band = min(today's open, yesterday's close) × (1 − σ)
2. **Checks every half hour:** 10:00, 10:30, …, 15:30, using the price at that moment.
   - **Long** if the price is above **both** the upper band and VWAP.
   - **Short** if it's below **both** the lower band and VWAP.
   - **Otherwise flat.** Falling back inside the band, or through VWAP, closes the position.
     VWAP (the day's volume-weighted average price) acts as a trailing stop.
3. **Orders fill at the next minute's open.** Everything is closed at the 4:00 close with a
   market-on-close order.
4. **Sizing:** once a day, aim for 2% daily volatility, using QQQ's last 14 days, capped at 4x
   leverage. The same share count is used all day.

**Worked example:** QQQ opens at $500 after closing at $498 yesterday. At 10:00, σ (the
typical move by 10:00) is 0.4%. The upper band is $500 × 1.004 = $502.00 and the lower band
is $498 × 0.996 = $496.01. If QQQ is at $502.50 with VWAP at $501.20, it's above both, so go
long. At 10:30, if it has slipped to $501.80 (below the $502.00 band), go flat.

**How it has done** (the other agent's run, $5k, IBKR Tiered, 0.5¢ slippage):

| Period | CAGR | Sharpe | Max drawdown |
|---|---|---|---|
| All (Oct 2021 – Sep 2026) | 18.7% | 1.33 | −16% |
| After publication (from May 2024) | 15.3% | 1.02 | −16% |
| QQQ buy & hold, after publication | 23.2% | 1.08 | −23% |

- **Before costs it makes +5.8 basis points per trade after publication, and it's positive in
  every year.**
- **Caveats (the other agent's own):** QQQ was checked because SPY failed, which is a
  selection risk; slippage is an assumed 0.5¢, not measured; and there's only ~2.3 years of
  post-publication data.
- It uses a lot of leverage (1.8x on average, up to 4x), which matters when it's combined with
  other sleeves (Part 4).

## Part 3: the stock ORB, in one paragraph

At 9:35, rank all US common stocks by opening-range relative volume and take the top one. Place
a stop-limit order at its first 5-minute candle's high (if the candle was green) or low (if red).
Stop 1 ATR away; otherwise hold to the close. Risk 1% of the account per trade. Realistic
backtest: 12% CAGR, Sharpe 0.70. Everything else is in *ORB experiments* and *ORB parameter grid*.

## Part 4: combining them (from *Combining strategies*)

- **Splitting the $5k into separate pots hurts** the intraday sleeves: at $1,500, per-order
  minimums eat them.
- **Overlaying works better:** intraday sleeves are flat every night, so in one margin account
  they can trade off the full $5k while the daily book holds its positions. Margin interest is
  only charged on end-of-day balances, so intraday leverage is free.
- **The limit is IBKR's 4x intraday cap:** daily book (≤1x) + ORB (~0.25x average) + QQQ noise
  (up to 4x) is too much, so QQQ noise would need a lower volatility target (roughly half).

## Part 5: execution, backtest vs live

### In the backtests (what every number above assumes)

| | Daily book | Stock ORB | QQQ noise |
|---|---|---|---|
| Decision | Close of day t | 9:35 opening range, then each minute | Every half hour from 10:00 |
| Entry order | Market at the next open | Stop-limit at the breakout level | Market, next minute's open |
| Fill model | Open ± 5 bps | The limit price, from 1-second bars (can miss) | Open + 0.5¢ |
| Exit | Next rebalance | Stop-market (measured ~4¢ slippage) or MOC at the close | Next signal, or MOC at the close |
| Costs | IBKR Tiered | IBKR Tiered | IBKR Tiered |

### Live: what exists today and what doesn't

**Built:**
- `uv run python -m horizon_trader.run_daily --dry-run` fetches today's closing prices,
  computes each sleeve's targets, nets and caps them, and prints the orders it **would** send.
  It starts from an empty, simulated account every time, so it doesn't yet know your real
  holdings.
- `uv run python -m horizon_trader.execution.ibkr` checks the connection to IB Gateway in
  **read-only** mode: it lists accounts, balances and positions, and cannot place orders.

**Not built yet:**
1. **The IBKR order adapter** (next step, using `ib_async`): read real positions, send the
   orders, confirm fills, reconcile what IBKR says we hold against what the system thinks,
   and a kill switch. Nothing places real orders until you give an explicit go-ahead,
   starting with the paper account.
2. **Scheduling:** the daily run after the close (targets) and order submission at the next
   open (market-on-open or market orders), running unattended on the Linux box later
   (`deploy/` has a systemd timer draft).
3. **Intraday engines:** the ORB and QQQ-noise backtests exist, but live versions don't.
   Two practical blockers:
   - **Real-time data.** Our Massive plan is **15-minute delayed**, so it can't pick the
     stocks at 9:35 live. The ORB would need IBKR real-time market data plus IBKR's market
     scanner (to rank opening volume across stocks), or Massive's real-time tier ($199/month).
     QQQ noise only needs QQQ's live bars, which an IBKR data subscription covers.
   - **Order handling during the day:** stop-limit entries, protective stops, market-on-close
     exits, and keeping total intraday exposure under 4x. NautilusTrader (event-driven, with
     an IBKR adapter) is the candidate for this part.

### Suggested order of work

1. IBKR paper adapter for the **daily book** first (few orders, simplest).
2. **QQQ noise** on the paper account (one instrument, needs only live QQQ bars).
3. **Stock ORB** on the paper account last (needs real-time scanning of the whole market).

## Glossary

| Term | Meaning |
|---|---|
| ATR | Average True Range: a stock's typical daily move in dollars (14-day average) |
| Basis point (bp) | 0.01%. 5 bps of slippage on a $100 share = 5¢ |
| CAGR | Compound annual growth rate |
| Max drawdown | Largest peak-to-trough loss |
| MOC | Market-on-close order: fills at the official 4:00 closing price |
| R | The risk on a trade: entry-to-stop distance × shares. "+2R" = made twice what was risked |
| Relative volume | Today's opening-range volume ÷ its 14-day average |
| RSI(2) | Relative Strength Index over 2 days: 0 = sharply sold off, 100 = sharply bought |
| Sharpe | Return per unit of volatility (annualized). About 0.7 for SPY; above 1 is good |
| Slippage | Paying a worse price than planned, per share |
| VWAP | Volume-weighted average price of the day so far |

## Sources

- Jegadeesh & Titman (1993), Returns to Buying Winners and Selling Losers. https://doi.org/10.1111/j.1540-6261.1993.tb04702.x
- Moskowitz, Ooi & Pedersen (2012), Time Series Momentum. https://doi.org/10.1016/j.jfineco.2011.11.003
- Moreira & Muir (2017), Volatility-Managed Portfolios. https://doi.org/10.1111/jofi.12513
- Zarattini, Aziz & Barbon (2024), Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172
- Zarattini, Barbon & Aziz (2024), A Profitable Day Trading Strategy for the U.S. Equity Market. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
