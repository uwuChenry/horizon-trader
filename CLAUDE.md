# horizon-trader

Personal systematic trading system. Python 3.12, managed with `uv`, runs on Windows now and on a Linux box later. Broker is IBKR.

## Owner's constraints and goals
- IBKR Pro account, **under $5k**. Mainly US stocks and ETFs; possibly small crypto and options later (options defined-risk only).
- Horizons: **swing (days to weeks) and position (weeks to months)** for the core, plus **intraday strategies with a few trades a day** (e.g. opening-range breakout), which are in scope. HFT and market-making are out of scope: that's the territory of firms like Jane Street and HRT.
  - The $25k Pattern Day Trader minimum was removed by FINRA Regulatory Notice 26-10 (effective 2026-06-04). It's replaced by intraday margin rules; Reg T's $2,000 minimum still applies to margin and short sales. Brokers can phase this in until 2027-10-20, so check the account's PDT status before relying on it.
  - The owner is international, so **IBKR Pro only** (IBKR Lite and Schwab retail accounts are US-residents only). Default plan is **Tiered** ($0.35 minimum per order, vs $1 on Fixed). An intraday edge must be measured per trade in dollars, after commissions **and** slippage.
  - US dividends are withheld for non-US holders (30% default, lower under a tax treaty). This isn't modeled yet: the backtests use dividend-adjusted prices (about -0.4%/yr on SPY at 30%).
  - Alternative API broker for internationals: Alpaca ($0 commission, paper account, 195+ countries). Margin, shorting and fees for the owner's country are unverified. Firstrade has no official API; moomoo's non-US fees (0.03% + $0.99/order) are worse than Tiered.
- Prefers large caps over small or penny stocks.
- Long-term goal: turn published quant papers into testable strategies. LLMs (Claude) are used for research and, later, as a signal source.
- Wants honest evidence over flattering backtests. Report bad results plainly.

## Commands
```bash
uv sync                                                        # dev + dashboard groups by default; add --group research for vectorbt/lightgbm/jupyter
uv run pytest                                                  # ~171 tests, <10s, no network
uv run ruff check . && uv run ruff format .                    # line length 100
uv run python -m horizon_trader.run_daily --dry-run            # today's targets and orders (live mode refuses until the IBKR adapter exists)
uv run python -m horizon_trader.backtest.run [--plan fixed] [--save]   # every sleeve + combined + SPY, 2008 to today
uv run python -m horizon_trader.backtest.robustness            # param grids, first vs second half, walk-forward, correlations (~70s)
uv run python -m horizon_trader.execution.ibkr                 # READ-ONLY IBKR connection check
uv run python -m horizon_trader.data.massive check            # verify Massive S3 keys
uv run python -m horizon_trader.data.massive download [--dataset minute|day] [--start YYYY-MM-DD]  # resumable
uv run python -m horizon_trader.data.massive_ref            # splits + common-stock list (REST, MASSIVE_API_KEY)
uv run python -m horizon_trader.intraday.orb [--rebuild]     # ORB on Stocks in Play, full report (~3 min first run)
uv run python -m horizon_trader.intraday.orb --stops 0.1,0.5,1.0  # stop-width robustness check
uv run python -m horizon_trader.intraday.slippage [--top 2 --stop 1.0] [--compare]  # measured fills from 1-second bars; --compare = account x plan x order type
uv run python -m horizon_trader.intraday.orb_ideas [--save]      # pre-registered ORB ideas (~25s)
uv run python -m horizon_trader.intraday.orb_grid [--save]       # 480-config grid x 4 slippage x 2 accounts, train/test (~45s)
uv run python -m horizon_trader.intraday.orb_ideas --round 2    # gap catalyst + volatility regime ideas
uv run python -m horizon_trader.intraday.orb_largecap           # dollar-volume (large-cap) filters, own measured slippage
uv run python -m horizon_trader.intraday.etf_orb [--tickers ...] # ORB on QQQ/SPY/TQQQ/SPXL/UPRO/SOXL/SMH (~90s)
uv run python -m horizon_trader.backtest.mix [--save]           # daily book + intraday sleeves: splits and overlays
uv run python -m horizon_trader.backtest.megacap [--save]       # top 10/50/100 by point-in-time market cap vs SPY/QQQ/OEF/XLG
uv run python -m horizon_trader.backtest.winners [--save]       # momentum top 10/20 among the point-in-time 200 largest, $5k net
uv run python -m horizon_trader.intraday.market_momentum [--ticker QQQ] [--save]  # SPY noise-area + last-half-hour momentum (~90s)
uv run python -m horizon_trader.macro.gold_dollar [--save]      # gold vs dollar (GLD/UUP), 5 pre-registered tests (~2.5 min)
uv run python -m horizon_trader.alphas.cli extract <pdf|url>   # paper -> research/alphas/*.yaml (needs ANTHROPIC_API_KEY)
uv run python -m horizon_trader.alphas.cli evaluate <yaml...>  # rank-IC report on the large-cap universe
uv run python -m horizon_trader.alphas.cli backtest <yaml> <alpha>
```
Any backtest command accepts `--config <file>` to try an experimental setup without editing `config/settings.yaml`.
`--save` on `backtest.run`, `intraday.orb`, `intraday.slippage` and `intraday.market_momentum` writes result bundles; browse them with:
```bash
uv run python -m horizon_trader.dashboard                      # Streamlit app on localhost:8501 (+ Research page)
```

## Architecture (the core contract)
`data -> sleeves -> portfolio (net + risk caps) -> execution (trade the difference)`

- **Sleeves** (`sleeves/`) output **target weights, never orders**.
  - Subclass `PanelSleeve` and implement `weights_history(prices) -> date x ticker DataFrame`, where row t uses only data up to t.
  - The live daily run takes the last row of the same function, so backtest and live share one code path.
  - Register new sleeve types in `SLEEVE_TYPES` (`sleeves/__init__.py`), configure them in `config/settings.yaml`, and add a parameter grid in `backtest/robustness.py:PARAM_GRIDS`.
- **Portfolio layer** (`portfolio/`): scales each sleeve by its allocation, nets positions per ticker, then applies the per-name cap and gross limit. Each function has a single-day (Series) version and a history (DataFrame) version, and a test keeps the two identical.
- **Execution** (`execution/`):
  - `compute_orders` handles the rebalance band, dust filter and sells-first ordering, and is shared by the daily run and the backtester.
  - `PaperBroker` is the in-memory simulator, with the cost models in `costs.py` (rates verified 2026-09-24). `CostModel.total()` = commission + `fees()`, and every fill pays the total.
    - **Tiered** (the default): $0.0035/share up to 300k shares/month, $0.35 minimum, plus clearing $0.0002/share and an **assumed** $0.003/share exchange remove-liquidity fee.
    - **Fixed**: $0.005/share, $1 minimum, 1% of value maximum, exchange and clearing included.
    - Both pay SEC ($20.60 per $1M sold) and FINRA TAF ($0.000195/share sold) on sells.
    - Check the Tiered exchange-fee assumption against real paper fills.
  - The `Broker` protocol is the seam where the real IBKR adapter plugs in. NautilusTrader is the candidate engine for intraday strategies (event-driven fills, stop orders, IB adapter).
- **Backtest** (`backtest/sim.py`): signals from the close of day t trade at the open of day t+1. Targets are re-applied daily through `compute_orders`, so a position is traded back once it drifts past the 2% band. `PaperBroker` allows slightly negative cash (overweight positions inside the band plus new buys) and charges no margin interest: 0.6% of equity on average in the momentum top 10.
- **Data** (`data/store.py`): OHLCV cached per symbol as Parquet under `./data` (or `$HT_DATA_DIR`), refreshed once a day from yfinance. yfinance is a prototype source only: it has no delisted tickers (survivorship bias).
- **Intraday data** (`data/massive.py`): Massive flat files, one Parquet per trading day under `data/massive/<minute|day>/<YYYY>/`, covering the whole US market including delisted names. Prices are **unadjusted** and timestamps are bar starts in New York time. The Starter plan ($29/mo) covers 5 years. Personal use only; delete the data if the account is terminated.
- **Intraday research** (`intraday/`): `features.py` builds split-safe daily stats (ATR, average volume) and the opening range / relative volume from Massive bars. `orb.py` simulates each candidate's trade once, caches the trade table under `data/massive/derived/`, then runs portfolio variants (size, costs, slippage) on it in seconds. Pass `--rebuild` after changing simulation code.
  - **Speed and caches:**
    - `build_trades` returns straight from cache (~0.1s) when every day is done; processed days are tracked in `*.days.json`.
    - Missing days, rebuilds and opening ranges run in parallel worker processes (`orb.workers()` = cores - 2).
    - `orb.CandidateBars` is one cached file with every candidate's session bars (`cand_bars_or5.parquet`, ~1 GB in memory, 3s to load). Use it instead of reading day files per ticker: a filtered read decodes the whole 1.5M-row file.
    - `orb_ideas` runs variants in a process pool: 15 variants in ~25s (was ~10 min). Results are verified identical to the serial version.
    - **Windows:** worker processes re-import the main script, so run parallel code via `python -m ...` or behind `if __name__ == "__main__":`, never from stdin.
  - `market_momentum.py` caches one ticker's session bars (`derived/minute_<T>.parquet`), reshapes them into day x minute matrices (`make_bars`), and builds cost-free trade tables that `run_portfolio` sizes and charges. Signals use the close of the minute ending at a check time and fill at the next bar's open. Exits at the close use the Massive daily close, which is the official closing auction (checked against the minute bars).
- **Results and dashboard:**
  - `backtest/bundle.py`: every backtest saves the same bundle under `data/results/<timestamp>_<name>/`: equity, trades (one row per round trip), benchmark, and meta.json (params, caveats, `oos_start`, git commit).
  - `backtest/analytics.py` computes every metric the dashboard shows (profit factor, streaks, drawdown periods, in-sample vs out-of-sample split, FIFO round trips from fills). It's tested, so the dashboard and CLI can't disagree.
  - `dashboard/app.py` (Streamlit) only displays. Figure builders live in `dashboard/charts.py`, and the colours follow the validated dataviz palette.
  - A new strategy shows up in the dashboard by writing a bundle via `save_run`.
  - `dashboard/nav.py` is the entry point, with three pages: Backtests (`app.py`), Holdings (`holdings.py`) and Research (`research.py`).
  - Holdings shows what a portfolio held on any day (date slider), for bundles with a `holdings` table. `save_run(..., tables={...})` stores extra tables under `tables/`. `winners --save` writes `holdings` (daily positions rebuilt from the fills) and `picks` (each month's top-20 ranking). Page logic lives in `dashboard/holdings_view.py`.
  - Research renders every `research/*.md` note and has a Papers tab that collects every link the notes cite (`dashboard/notes.py` parses markdown links and bare URLs).
  - Write findings there, not only in chat, and link every paper you cite.
  - Intraday portfolios need the full trading calendar passed to `orb.run_portfolio` when the trade table holds only traded days; otherwise flat days drop out and Sharpe is distorted.
- **Alpha research** (`alphas/`):
  - `dsl.py` is the safe formula language: parsed with `ast`, **never eval'd**, with every operator causal. LLM-written formulas go through it.
  - `library.py` defines the YAML formula libraries. Each formula's **claimed direction is recorded before testing**, so a signal that only works flipped shows up as negative IC.
  - `evaluate.py` computes rank IC. 2024 onward is the **holdout**, hidden unless `--holdout` is passed.
  - `extract.py` sends the PDF to Claude (`claude-opus-5`, structured JSON output, `fallbacks="default"`).
  - `sleeves/alpha.py` trades any formula as a top-N sleeve.

## Rules for changes
- No lookahead, ever. Any new sleeve or DSL function gets a truncation test ("cutting off the future doesn't change row t"); copy the pattern in `tests/test_sleeves.py` or `tests/test_alphas.py`.
- Don't tune parameters to backtest results. Use textbook or paper defaults and check them with `robustness`. Walk-forward re-tuning has never beaten fixed defaults here.
- Judge stock-selection alphas against the **equal-weight row of the same universe**, not SPY: `config/universes/us_large_cap.yaml` is today's large caps and is survivorship-biased.
- Always compare with and without costs. At $5k, the per-order minimum dominates.
- LLM signals are **forward-test only**: a backtest can't be trusted because the model may remember what happened after its training cutoff. Log every LLM output with a timestamp.
- Secrets live only in `.env` (git-ignored). `data/` is git-ignored.

## What the evidence says so far (2008 to 2026, $5k, IBKR Tiered pricing)
| Sleeve | CAGR | Sharpe | Max DD | Verdict |
|---|---|---|---|---|
| combined book (0.3/0.25/0.2/0.15) | 6.5% | 0.83 | -12% | Fixed pricing: 5.8%, 0.75. Tiered cuts 18-year commissions from $1,435 to $532 |
| position_momentum (ETF 12-1 rotation) | 9.9% | 0.76 | -18% | Core. Only the 12-month lookback is robust; 6-month/top-2 blew up to a -45% drawdown |
| position_volmanaged (SPY, Moreira-Muir) | 9.7% | 0.81 | -21% | Most robust (Sharpe 0.66-0.80 across the grid, 1.00 out-of-sample from 2013). 0.81 correlated with SPY |
| position_trend (TSMOM, inverse-vol) | 5.0% | 0.73 | -14% | Stable but **0.85 correlated with momentum**, so largely redundant |
| swing_meanrev (RSI(2)) | 2.7% | 0.49 | -19% | Weak at every setting and costly. Lowest correlation to the others |
| MACD 12/26/9 (SPY/QQQ/IWM) | 4.8% | 0.44 | -26% | Below buy-and-hold even with zero costs. Not in config |
| SPY buy & hold | 11.3% | 0.64 | -52% | Benchmark |

**5-minute ORB on Stocks in Play** (Massive minute bars, Oct 2021 to May 2026, all US common stocks incl. delisted; preliminary):
- Before costs, the signal replicates: average R rises with relative volume (+0.10R at 2-3x, +0.55R above 30x), in both 2021-23 and 2024+ (after publication).
- Minute bars can't resolve it: 52% of trades touch the 14-cent median stop inside the entry minute. Average R is -0.29 (stop counted), +0.27 (bar-direction guess) or +0.18 (ignored). Second bars (available on Starter via REST) can settle this.
- It's fragile to slippage: $25k top-20 at IBKR Fixed goes from Sharpe 2.1 (0c) to 0.39 (1c) to wiped out (2c). The best 5% of trades carry 300% of total R.
- Stop width (`--stops`, robustness check only): the edge per share before costs barely changes with the stop (top-20 about 4-7 cents, top-2 about 10-16 cents), so wider stops don't fix per-share costs. They do remove the minute-bar ambiguity (0.2% of trades at a 1 ATR stop) and cut drawdowns. The most trustworthy row: $5k top-1, 1 ATR stop, 1c slippage gives 12% CAGR, Sharpe 0.71, -22% max DD (SPY over the same period: 11%, 0.69); at 3c it's 6% and 0.42. Slippage is still assumed, not measured.
- **Measured slippage** (1-second bars, 1,980 top-2 entries and 574 stop-outs): the median is ~0 but the tail is fat. Mean entry slippage is 1.7c at the trigger-second VWAP, **4.5c at the next second's open** (the realistic estimate for a retail stop order), and 6.8c at the worst print. These are floors, because second bars don't show the bid/ask spread. At the next-second estimate, $5k top-1 with a 1 ATR stop gives **6% CAGR, Sharpe 0.42**; top-2 gives 3%, Sharpe 0.24. SPY over the same period: ~11%, 0.69. The $1 minimum commission (~$2 per round trip) eats about half of the remaining edge. **Verdict: not worth trading at $5k with stop-market orders.**
- Order type and account (`slippage --compare`, top-1, 1 ATR stop, measured fills): a stop-limit entry at the trigger price fills 97% of trades. It misses the 3% that run away, which average +1.4R. Sharpe is bounded by fill assumptions (worst case: fill at the limit, the code default; best case: fill at the next trade, approximate): $5k Fixed 0.52-0.78 (stop-market 0.42); $20k Fixed 0.79-1.0 (0.70); IBKR Lite 0.87-1.08 (0.78). Wider limits (+5c, +10c) are worse under the worst-case assumption. The $20k account helps because the $1 minimum stops dominating. Lite's MOC exits exceed its 10% free-auction allowance, so they're charged $0.005/share. Lite's order routing and API access for stop orders are unverified. Many variants were compared on the same 5 years, so the best rows are optimistic: paper-trade before believing any of them.
- $5k top-1/top-2 at 1c: 37-55% CAGR but Sharpe 0.7-0.84 and 53-69% drawdowns, using 4x intraday leverage on one or two stocks.

**SPY market intraday momentum** (`intraday.market_momentum`, Oct 2021 to Sep 2026, paper defaults; full write-up in `research/strategy_survey.md`):
- **Noise area** (Zarattini, Aziz & Barbon 2024):
  - Replicates inside the paper's own sample (to May 2024): +5.4 bps/trade, t = 2.9.
  - After publication: +1.3 bps/trade, t = 0.7. 2026 so far is negative.
  - $100k at paper costs: Sharpe 1.21 overall, 0.52 after publication.
  - $5k IBKR Fixed at 0.5c slippage: 8.0% CAGR, Sharpe 0.62, and -2.9% after publication. Tiered: 12.5%, and 2.2% after publication. SPY: 11.2%.
  - The $1 minimum is about $2.30 of the ~$2-4 gross per trade.
  - **Verdict: not worth trading on SPY at $5k now.**
  - **QQQ robustness check:** the effect holds after publication: +5.8 bps/trade, t = 2.0, positive every year. $5k Tiered at 0.5c: 18.7% CAGR, Sharpe 1.33 overall; 15.3% and 1.02 after publication, vs QQQ buy-and-hold at 23.2% and 1.08. Picking QQQ because SPY failed is selection bias. The owner skipped an IWM/DIA cross-check, so the only remaining out-of-sample test is paper trading QQQ on IBKR.
- **Last-half-hour momentum** (Gao et al. 2018; Baltussen et al. 2021): dead. The rest-of-day signal is +1.4 bps before May 2024 and -1.4 bps after; the first-half-hour signal is noise. The always-long control is flat.

**Gold vs dollar** (`macro.gold_dollar`, GLD vs UUP, 2007-2026; write-up in `research/gold_dollar.md`):
- The same-day inverse link is real and stable: daily correlation between -0.2 and -0.65 in every year, including 2022-26.
- It is **not tradeable**. None of the 5 pre-registered tests passed: the dollar leading gold (1 or 5 days) has the wrong sign, and gap-closing over 5 days, 20 days or at the level has t <= 1.4.
- Long/flat versions don't beat GLD buy-and-hold (Sharpe 0.57).
- Use UUP, not DXY: DXY settles an hour after GLD's close, which creates a fake lead.

**Mega-cap portfolios** (research/megacap.md): 2008-2026 index funds: top 50/100 (XLG/OEF/MGC) ~11.8% vs SPY 11.4%, same ~50% drawdowns; QQQ 16.4%. Point-in-time top 10 (Massive market caps) Oct 2021-Sep 2026: 15.9% vs SPY 11.0% (price only) with a -37% vs -25% drawdown; TODAY's top 10 bought in 2021 shows 35.1%, which is pure hindsight. Point-in-time market caps are cached at data/massive/reference/market_caps.parquet.

**Large-cap momentum, point-in-time** (research/winners_momentum.md): 12-1 momentum, top 10 of the 200 largest (point-in-time, incl. delisted), Oct 2022-Sep 2026, $5k net: 45.4% CAGR, Sharpe 1.14, -40% max DD, beta 1.61. That beats the equal-weight universe (1.06) but slightly trails SPY levered 1.61x (1.22). It caught 14 of the 15 biggest winners, mostly late. July 2026 lost 27%. The same rule on today's 200 largest shows 87%: survivorship nearly doubles it. A short, bull-market-only sample; validate on 2016-2021 before use. **Data trap:** Massive's daily files key on ticker, so a reused symbol joins two securities (BNY was a muni fund before BNY Mellon took it in 2026; SPCX was a SPAC ETF before SpaceX). `winners.momentum` returns NaN when a window has more than 10 missing days. Any new price-history signal needs the same guard.

Alpha research on ~100 large caps, 2010-2023: none of the 20 variants reached t > 2 in the claimed direction.
- 12-month momentum and 1-week reversal each came in at t ~ 1.95.
- The Kou et al. (arXiv 2409.06289) formulas are mostly noise; their 14-day momentum predicts the wrong way.
- Low-volatility has the wrong sign, which is survivorship bias at work.
- Top-3 momentum shows 33% CAGR, but its Sharpe equals equal-weight's, so the extra return is survivors plus concentration.
- Weekly reversal is destroyed by commissions ($11k on a $5k account).

## Current status and next steps
- **Pending decision:** make momentum + vol-managed the core, merge or cut the trend sleeve, and replace the swing sleeve with something uncorrelated. The allocations in `config/settings.yaml` still hold all four sleeves (0.3/0.25/0.2/0.15, with 10% reserved for the LLM sleeve).
- **IBKR paper account:** the owner is setting up IB Gateway (paper, port 4002, `.env` from `.env.example`). Once `execution.ibkr` connects, the next step is the order-placing `Broker` adapter using `ib_async`, with reconciliation and a kill-switch. Place **no live orders** without an explicit go-ahead.
- **Alpha extraction:** code is done and unit-tested with a mocked client, but it has **never run against the real API** (no key on this machine yet).
- **Paper-trading plan (from research/portfolio_mix.md):** daily book as the core, with the ORB baseline and QQQ noise-area momentum (at a reduced vol target) overlaid on the same margin account, total intraday gross under 4x. Needs a margin account with intraday leverage.
- **ORB:** best realistic setup is top-1, 1 ATR stop, stop-limit entry at the trigger, IBKR Pro Tiered ($5k: 12.2% CAGR, Sharpe 0.72, -22% max DD). That's roughly SPY-like Sharpe with no market correlation.
  - Pre-registered ideas (`intraday/orb_ideas.py`, 14 variants, pass = beats the baseline in both 2021-23 and 2024-26):
    - **Entry cutoff** (10:00/10:30/11:00) passed at every setting: Sharpe 0.83-0.85. It drops ~15-30 late trades a year.
    - **Relative volume** >= 5/8/12 passed: Sharpe 0.73/0.78/0.88. >= 3 changes nothing because the top-1 stock is always above 3.
    - **Failed badly:** trading with SPY's direction (0.41), breakeven stops (-0.15 to 0.68) and trailing stops (-1.77 to 0.45). Capping the runners destroys the edge.
    - No idea raised the win rate (~44%).
  - **Round 2 and large caps** (research/orb_experiments.md, Experiments 8-10): large-cap dollar-volume floors ($50M-$250M/day) cut slippage in bps (14 -> 5) but raise it in cents and kill the edge (Sharpe 0.70 -> -0.03 to 0.18). The overnight-gap catalyst proxy and the volatility-regime filter both fail the pre-registered rule; high-vol-only halves the drawdown at the same Sharpe.
  - **ETF ORB** (research/etf_orb.md): QQQ/SPY/TQQQ/SPXL/UPRO/SOXL/SMH x the 2023 paper's rules, our baseline, and the paper's 5%-ATR optimum. Slippage is small on ETFs (0.5-4c), but the edge is gone in 2021-26: the paper replication at its own zero-cost assumptions gives QQQ Sharpe 0.46 (paper 1.12). At $5k measured, 19 of 21 lose money; buy-and-hold wins everywhere. The 5%-ATR 'optimum' is worst (-0.35 to -2.44).
  - **Combining** (research/portfolio_mix.md): the intraday sleeves are ~uncorrelated with the daily book (<= 0.06), but splitting $5k into pots hurts because intraday sleeves degrade at small sizes (ORB Sharpe 0.74 at $5k, 0.38 at $1.5k). Overlaying them on the same margin account (flat overnight, no interest) is the structural fix: daily book 0.91 -> +ORB 1.00, +QQQ noise 1.69 (not pre-registered). QQQ noise uses up to 4x alone, so it must be sized down to fit IBKR's 4x intraday cap next to the daily book.
  - **Parameter grid** (`orb_grid.py`, research/orb_parameter_grid.md): picking the best of 480 configs on 2021-23 lost to the untouched baseline on 2024-26 in all 8 slippage x account cases; deflated Sharpe 0.00-0.48, so nothing is significant after 480 tries. Robust everywhere: hold to the close (every profit target hurt) and a ~1 ATR stop (0.25-0.75 fail out of sample). Candidate to validate: relvol >= 12 + no entries after 10:30 (full-period Sharpe 0.94, $5k measured). Slippage moves the baseline's test Sharpe more than any parameter: 1.05 at 0c, 0.94 at 1c, 0.82 measured stop-limit, 0.53 measured stop-market.
    - Caveat: over ~2.5-year halves the standard error of Sharpe is ~0.6, so +0.1-0.15 improvements are within noise. Confirm on untouched data (2016-2021 via one month of Massive Developer) or in paper trading before adopting.
- **Candidate next strategies:**
  - **5-minute ORB on Stocks in Play** (Zarattini, Barbon & Aziz 2024, SSRN 4729284). The paper claims a 2.81 Sharpe, but it models commissions only: no slippage, borrow cost or short-sale restriction. The 5-minute window was the best of the four it tested (the 30-minute had a Sharpe of 0.21). Replicate with and without 1-2 cents of slippage per side before building anything live. It needs 1-minute bars for the whole market, including delisted names.
  - ~~Intraday momentum~~: tested, see the evidence above.
  - Post-earnings-announcement drift: the classic version is dead in large caps since ~2006 (Martineau 2022). The text-based surprise (PEAD.txt, *JFQA* 2023) still drifts, which makes it the natural LLM use, forward-test only.
  - Earnings announcement premium (Frazzini & Lamont 2007; persists among the largest announcers) and return seasonalities (Keloharju et al. 2016): cheap daily-data tests. Ranking and dead ends are in `research/strategy_survey.md`; LLM-strategy papers are in `research/llm_strategies_survey.md`.
- **Data:** yfinance returned no data for BK ("quote not found"), possibly transient. For proper stock-universe research, a point-in-time source with delisted names (e.g. Norgate) is the upgrade. For intraday history, the options are Massive (formerly Polygon.io) or Databento (usage-based, with $125 of free credits); IBKR historical bars are rate-limited.
- **Deploy later:** `deploy/` has a Dockerfile, a docker-compose placeholder (the IB Gateway image and ports are unverified) and a systemd timer. Recommended host is an x86 mini PC or VPS, not a Jetson Nano.
