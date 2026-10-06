# horizon-trader

Personal systematic trading system. Python 3.12, managed with `uv`, runs on Windows now and on a Linux box later. Broker is IBKR.

## Owner's constraints and goals
- IBKR Pro account, **under $5k**. Mainly US stocks and ETFs; possibly small crypto and options later (options defined-risk only).
- Horizons: **swing (days to weeks) and position (weeks to months)** for the core, plus **intraday strategies with a few trades a day** (e.g. opening-range breakout), which are in scope. HFT and market-making are out of scope: that's the territory of firms like Jane Street and HRT.
  - The $25k Pattern Day Trader minimum was removed by FINRA Regulatory Notice 26-10 (effective 2026-06-04). It's replaced by intraday margin rules; Reg T's $2,000 minimum still applies to margin and short sales. Brokers can phase this in until 2027-10-20, so check the account's PDT status before relying on it.
  - The owner is international, so **IBKR Pro only** (IBKR Lite and Schwab retail accounts are US-residents only). Default plan is **Tiered** ($0.35 minimum per order, vs $1 on Fixed). An intraday edge must be measured per trade in dollars, after commissions **and** slippage.
  - **ORB research assumption (owner, 2026-10-02): Tiered and $0.01/share slippage per entry/non-auction exit.** The EMA follow-up keeps 5-minute entries and tests EMA(12) exits on 15-minute candles. These are research assumptions; see `research/orb_ema.md`. The daily book's basis-point slippage setting is separate.
  - US dividends are withheld for non-US holders (30% default, lower under a tax treaty). This isn't modeled yet: the backtests use dividend-adjusted prices (about -0.4%/yr on SPY at 30%).
  - Alternative API broker for internationals: Alpaca ($0 commission, paper account, 195+ countries). Margin, shorting and fees for the owner's country are unverified. Firstrade has no official API; moomoo's non-US fees (0.03% + $0.99/order) are worse than Tiered.
- Prefers large caps over small or penny stocks.
- Long-term goal: turn published quant papers into testable strategies. LLMs (Claude) are used for research and, later, as a signal source.
- Wants honest evidence over flattering backtests. Report bad results plainly.

## Commands
```bash
uv sync                                                        # dev + dashboard groups by default; add --group research for vectorbt/lightgbm/jupyter
uv run pytest                                                  # ~341 tests, <10s, no network
uv run ruff check . && uv run ruff format .                    # line length 100
uv run python -m horizon_trader.run_daily --dry-run            # today's targets and orders (no state, no broker)
uv run python -m horizon_trader.run_daily --mode shadow|what-if|paper  # forward test: own simulator / IBKR what-if (places nothing) / IBKR paper MOO orders; run after 16:10 ET or pre-market
uv run python -m horizon_trader.run_daily --kill               # kill switch on (data/live/KILL) + cancel every open order
uv run python -m horizon_trader.backtest.run [--plan fixed] [--save]   # every sleeve + combined + SPY, 2008 to today
uv run python -m horizon_trader.backtest.robustness            # param grids, first vs second half, walk-forward, correlations (~70s)
uv run python -m horizon_trader.execution.ibkr                 # READ-ONLY IBKR connection check
uv run python -m horizon_trader.datasources.massive check            # verify Massive S3 keys
uv run python -m horizon_trader.datasources.massive download [--dataset minute|day] [--start YYYY-MM-DD]  # resumable
uv run python -m horizon_trader.datasources.massive_ref            # splits + common-stock list (REST, MASSIVE_API_KEY)
uv run python -m horizon_trader.intraday.orb [--rebuild]     # ORB on Stocks in Play, full report (~3 min first run)
uv run python -m horizon_trader.intraday.orb --stops 0.1,0.5,1.0  # stop-width robustness check
uv run python -m horizon_trader.intraday.slippage [--top 2 --stop 1.0] [--compare]  # measured fills from 1-second bars; --compare = account x plan x order type
uv run python -m horizon_trader.intraday.orb_ideas [--save]      # pre-registered ORB ideas (~25s)
uv run python -m horizon_trader.intraday.orb_grid [--save]       # 480-config grid x 4 slippage x 2 accounts, train/test (~45s)
uv run python -m horizon_trader.intraday.orb_ideas --round 2    # gap catalyst + volatility regime ideas
uv run python -m horizon_trader.intraday.orb_largecap           # dollar-volume (large-cap) filters, own measured slippage
uv run python -m horizon_trader.intraday.orb_inverted [--brackets]  # fade/mirror/flipped ORB vs the baseline (~15s); --brackets = exploratory stop x target grid
uv run python -m horizon_trader.intraday.ema_vwap [--tickers SPY QQQ] [--zero]  # 5-min 12-EMA and EMA9 x VWAP(ohlc4) vs a long-all-day control; --zero = $0-commission broker (~2 min)
uv run python -m horizon_trader.intraday.etf_orb [--tickers ...] # ORB on QQQ/SPY/TQQQ/SPXL/UPRO/SOXL/SMH (~90s)
uv run python -m horizon_trader.intraday.orb_shortlist        # can a 50-name IBKR scanner / pre-market list find ORB's pick live? (~5 min)
uv run python -m horizon_trader.intraday.scanner_log capture|compare  # log IBKR scanner lists at 9:25/9:35 ET (read-only) / score vs the true pick
uv run python -m horizon_trader.intraday.orb_windows          # ORB with 10/15/30/60-minute ranges vs 5 (pre-registered; ~15 min first run)
uv run python -m horizon_trader.intraday.orb_live run [--what-if]  # PAPER ORB executor: start before 9:30 ET; scanner -> exact relvol -> bracket (STP LMT + 1-ATR stop + MOC)
uv run python -m horizon_trader.intraday.orb_live sync        # same evening: book ORB fills into data/live/orb, check flat
powershell -File deploy/windows/install_tasks.ps1             # weekday Task Scheduler jobs: 08:00 Massive download + scanner log, 18:00 shadow run
uv run python -m horizon_trader.backtest.mix [--save]           # daily book + intraday sleeves: splits and overlays
uv run python -m horizon_trader.backtest.megacap [--save]       # top 10/50/100 by point-in-time market cap vs SPY/QQQ/OEF/XLG
uv run python -m horizon_trader.backtest.winners [--save]       # momentum top 10/20 among the point-in-time 200 largest, $5k net
uv run python -m horizon_trader.intraday.market_momentum [--ticker QQQ] [--save]  # SPY noise-area + last-half-hour momentum (~90s)
uv run python -m horizon_trader.macro.gold_dollar [--save]      # gold vs dollar (GLD/UUP), 5 pre-registered tests (~2.5 min)
uv run python -m horizon_trader.backtest.leverage              # SMH 0-5x vs SOXL vs IBKR margin (Fed funds + 1.5%), 2000 to today (~5s)
uv run python -m horizon_trader.datasources.sec download [--no-text]   # SEC XBRL facts + 10-K text for every CIK ever in the PIT top 200 (SEC_USER_AGENT in .env; ~15 min, resumable)
uv run python -m horizon_trader.backtest.multifactor [--save]   # momentum/value/quality/low-vol/Lazy Prices composites + walk-forward ridge, PIT top 200 (~90s)
uv run python -m horizon_trader.llm.fundamentals export|run|check|evaluate  # monthly Claude fundamental scores, top 200, FORWARD test (claude -p or subagents; no API key)
uv run python -m horizon_trader.pwb.audit [--refresh]           # Papers With Backtest: recompute ~93 headline Sharpes from each page's NAV (net of T-bills, flags)
uv run python -m horizon_trader.pwb.dual_class                  # PWB #1: dual-class pairs, same-close vs next-close vs traded-days fills (~5s)
uv run python -m horizon_trader.pwb.short_vix                   # PWB short-VIX rule: VIX index vs VIXY/SVXY, full size and site-sized
uv run python -m horizon_trader.pwb.survivorship                # today's S&P 500 since 1990: EW + Most Diversified Portfolio vs RSP (~5 min)
uv run python -m horizon_trader.congress.archive               # STOCK Act trades (kadoa-org dataset, pinned), 69k trades 2014-2026
uv run python -m horizon_trader.congress.event_study [--save]  # copy-trading Congress: filing-date vs trade-date entry, Pelosi, NANC (~70s)
uv run python -m horizon_trader.social.archive [--ref HEAD]       # Serenity (@aleabitoreddit) posts -> cashtag mentions (pinned commit by default)
uv run python -m horizon_trader.social.event_study [--stance] [--save]  # every cashtag vs SMH/SPY + follower portfolios; --stance adds labels + 50-shuffle placebo (~4 min)
uv run python -m horizon_trader.social.stance export|check      # labelling batches for Claude subagents / coverage check
uv run python -m horizon_trader.alphas.cli extract <pdf|url>   # paper -> research/alphas/*.yaml (needs ANTHROPIC_API_KEY)
uv run python -m horizon_trader.alphas.cli evaluate <yaml...>  # rank-IC report on the large-cap universe
uv run python -m horizon_trader.alphas.cli backtest <yaml> <alpha>
```
Any backtest command accepts `--config <file>` to try an experimental setup without editing `config/settings.yaml`; experiments live in `config/experiments/` (e.g. `risk_parity.yaml`: the book with risk parity in place of the trend sleeve).
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
  - **IBKR paper adapter** (`execution/ibkr_broker.py`, `execution/ledger.py`, tests in `tests/test_live.py` with a fake IB):
    - Refuses any account not starting with `DU`; there is no live switch on purpose.
    - Sizes from a per-strategy `Ledger` (virtual `account.starting_cash`, `data/live/<strategy>/`), never NetLiquidation. Orders are market-on-open (`tif="OPG"`) tagged `orderRef=<strategy>`; `sync_fills` books executions by tag with IBKR's actual commission next to the model's and the day's open; `reconcile` stops on any position gap; caps in `live:` (settings.yaml) are checked for the whole batch before anything is sent; rejected orders raise.
    - The `shadow` ledger (`<strategy>_shadow`) fills the same orders at the next open with the cost model, so `fills.csv` of the two compares modeled vs IBKR fills.
    - **IBKR rejects fractional-size orders through the API (error 10243)**: paper trading needs `share_decimals: 0` (`config/experiments/whole_shares.yaml`). The 2008+ backtest barely changes (Sharpe 0.83 vs 0.82) because adjusted prices were low and the account grows, but at $5k today rounding misweights 11% of the book (SPY 22.5% -> 15.3%, QQQ and GLD -> 0); 4% at $10k.
    - Ledgers don't credit dividends.
  - The `Broker` protocol is the seam where the real IBKR adapter plugs in. NautilusTrader is the candidate engine for intraday strategies (event-driven fills, stop orders, IB adapter).
- **Backtest** (`backtest/sim.py`): signals from the close of day t trade at the open of day t+1. Targets are re-applied daily through `compute_orders`, so a position is traded back once it drifts past the 2% band. `PaperBroker` allows slightly negative cash (overweight positions inside the band plus new buys) and charges no margin interest: 0.6% of equity on average in the momentum top 10.
- **Data** (`datasources/store.py`): OHLCV cached per symbol as Parquet under `./data` (or `$HT_DATA_DIR`), refreshed once a day from yfinance. yfinance is a prototype source only: it has no delisted tickers (survivorship bias).
- **Intraday data** (`datasources/massive.py`): Massive flat files, one Parquet per trading day under `data/massive/<minute|day>/<YYYY>/`, covering the whole US market including delisted names. Prices are **unadjusted** and timestamps are bar starts in New York time. The Starter plan ($29/mo) covers 5 years. Personal use only; delete the data if the account is terminated.
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
  - `dashboard/nav.py` is the entry point, with four pages: Backtests (`app.py`), Holdings (`holdings.py`), ORB day (`orb_day.py`: one day's Stocks in Play and each trade on a TradingView-style minute chart, read from the cached ORB trade tables; logic in `orb_view.py`) and Research (`research.py`).
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

**Internet indicator rules** (research/ema_vwap.md, `intraday.ema_vwap`, SPY/QQQ 5-min bars Oct 2021-Sep 2026): the 12-EMA stop-and-reverse trades 13x a day for +0.09 bp (SPY) / -0.02 bp (QQQ) per trade before costs, so -24% / -33% a year net at $100k; long-only still -10% / -14%. EMA9 x session VWAP (ohlc4) long-only makes 6.1% gross on SPY, 2.7% net at $100k (Sharpe 0.32) vs being long 9:35-close at 2.6% (0.25); it passed the pre-registered rule on SPY only, 1 of 16 tests, and QQQ's edge vanished in 2024-26. At $5k everything loses to the $0.35 minimum. At a $0-commission broker (`--zero`, SEC/FINRA fees kept) V9 long-only on SPY makes +4.5%/yr at 0.5c fills (Sharpe 0.51, beats the control both halves) but the 12-EMA still loses (SEC fees alone exceed its edge). Buy and hold: SPY 12.4%, QQQ 16.1%; intraday rules miss the overnight return.

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

**Leverage on semis** (research/leverage.md, SMH/SOXL, $5k IBKR Pro, margin at Fed funds + 1.5%): growth-optimal leverage on SMH is 1.05x measured from 2000-06 (includes the dot-com -86%), 2.9x from 2010, 2.4x over the last 5 years. From 2000: 1x 10.9% CAGR, 2x 5.0%, 3x -12%, SOXL (synthetic before 2010, tracks the real fund at 0.997 correlation) turns $5k into $108. In 5-year windows the share hitting an 80%+ drawdown is 2% at 1x, 26% at 1.5x, 32% at 2x, 59% at 3x, 70% for SOXL. SOXL trails 3x SMH (39.9% vs 48.2% since 2010). A never-rebalanced 2x margin account got liquidated 5 times from 2000; monthly rebalancing got none. Verdict: more than ~1.5x on a semis-only position is too much.

**Papers With Backtest audit** (research/pwb.md, `pwb/`): the site's headline Sharpes (README top 61 of 1,687; the site's own median is 0.32 over 4,312 papers) are mostly mechanical.
- Its Sharpe doesn't subtract the risk-free rate while its NAV earns T-bills: the median of 93 audited pages drops from 1.06 to 0.70 net of T-bills. The famous 922 is a strategy that held nothing for 9 months after publication (full-history Sharpe 0.09).
- 23 of 93 back-test today's S&P 500 from 1990. Equal weight on today's members beats RSP (point-in-time) by +5.6%/yr in every year 2003-2026; that reproduces the site's Most Diversified Portfolio (24.7%/yr, Sharpe 1.17 vs RSP 10.7%, 0.71).
- #1, dual-class arbitrage (1.97): stale closes on B shares with 41-58% zero-volume days. Filling only when a leg trades cuts gross from 15.6% to 7.7%/yr; liquid pairs make +0.3%/yr gross and lose after costs.
- Short-VIX rule (1.64): shorts the untradeable VIX index. 3% SVXY + T-bills scores Sharpe 3.14 at rf = 0 but 0.45 net of T-bills; full size is ~0.5-0.7 with 87-94% drawdowns.
- Several rows don't implement their paper at all (euro-zone bond auctions = holding SPX) and one SPX-only monthly strategy (covered-call CEF, 28.7%/yr) looks like lookahead. Use the site for ideas, never for evidence.

**Copy-trading Congress** (research/congress.md, `congress/`, 10,115 disclosed stock/ETF purchases filed Oct 2021-Sep 2026): trades go public a median 32 days later (45-day STOCK Act limit; 33% file late). Buying every disclosed purchase after filing and holding 60 days: 6.5% CAGR at $100k vs SPY 12.4% (alpha -6.7%/yr); the average buy is -0.4% vs SPY at 60 days (median -1.8%). Pelosi copied as stock: 14.1%, Sharpe 0.60, -49% DD, beta 1.42 vs QQQ 16.1%/0.77. Trade-date 'lookahead' entry was not better, so '200%' trackers more likely come from copying her call options, cherry-picked windows or ranking members after the fact. Live NANC ETF: 22.6% vs SPY 20.2% since Feb 2023, alpha +0.9%. Hints worth a pre-registered retest: Senate buys (+1.2%/60d, t 2.07) and $250k+ buys (+6.6%/120d, t 1.89, n=80). The dataset also covers executive-branch officials; they're reported separately.

**Following Serenity / @aleabitoreddit** (research/serenity.md, `social/`, Jul 2025-Sep 2026, 5,692 cashtag events on US names, every cashtag treated as a buy):
- Following his posts made money but trailed SMH: first mention held 60 days = 34% CAGR net, Sharpe 0.94, -38% DD; SMH 88%, 1.90, -25%; SPY 19%, QQQ 28%. Top 10 most-mentioned in the last 20 days = 68%, 1.22 (added after seeing the other rules, so optimistic).
- The average call lagged SMH bought at the same minute: 60-day mean -8% vs SMH, median -17%, 29% beat it. A few 2-4x winners (MXL, AXTI, AAOI, SNDK) carry the mean.
- His posts don't move prices (median move 1 minute after an in-session post: 0.0%), so chasing isn't the cost. The 4,500% figure is self-reported and leveraged, and can't be checked.
- **With stance labels** (Claude Sonnet read all 13,010 mentions; bullish = buy, bearish = sell, neutral = nothing, long only): bearish calls trail SMH by 23.5% over 60 days (t = -7.5), so the sells carry the information. 'Bullish until bearish' = 48% CAGR, Sharpe 1.01, and 'bullish in the last 20 days' = 55%, 1.18. Both beat all 50 label shuffles. Still below SMH (88%, 1.90). After ~Jun 2026 (likely past the labeller's training data) bearish still lags (-5%/20d, n = 32) but bullish = neutral, so the edge is thin out of sample.
- Biased in his favour: deleted posts are missing and the sample is one AI-hardware boom. His top foreign names ($SIVE, $SOI, $IQE) have no US bars. Next: a forward test on posts after 2026-09-17, labelled as they arrive. Timestamps come from X snowflake ids, not scraped dates.

**Multi-factor, point-in-time top 200** (research/multifactor.md, `backtest.multifactor`, formations Oct 2022-Aug 2026, top 20, $5k net). Fundamentals come from SEC XBRL (`datasources/sec.py`): original 10-Ks only, usable the day after filing. Pre-registered: 2 of 3 tests failed, and nothing beat the equal-weight universe:
- **Equal-weight composite** of momentum, value (B/M + E/P), quality (GP/assets) and low vol: 7.1% CAGR, Sharpe 0.60, -13% DD, beta 0.52, vs the equal-weight universe at 15.3% and 1.06 gross. It's a defensive tilt that lags in a rally; low vol was the worst signal (IC -0.046).
- **Lazy Prices** (10-K text similarity, Cohen, Malloy & Nguyen) is the best single signal: 1.02 net, but IC t = 0.56. Composite 5 (+ lazy) reaches 0.81.
- **Walk-forward ridge (learned weights)** chased regimes: value-heavy after 2022, then buying the most volatile stocks, for beta 1.65, Sharpe 0.66 and a -37% DD. It lost to equal weights. Quality covers only ~122 of 200 names (banks, and segment-only cost tags). 4 years, one regime: nothing here is significant.

**Risk parity** (research/risk_parity.md, `sleeves/risk_parity.py`, AFP 2012, 1/vol over 3 years, unlevered, SPY/EFA/EEM/TLT/IEF/GLD/DBC): 5.8% CAGR, Sharpe 0.74, -18% DD vs the trend sleeve's 5.0%, 0.73, -14%. Only 0.59 correlated with momentum (trend: 0.85). Grid 0.65-0.74, positive in both halves. Swapping it in for trend lifts the combined book from 0.82 to 0.87. 2022: -12% vs trend's -5.6%. Not switched in settings.yaml; that's the owner's call.

**Arbitrage and quant styles, Q&A notes** (research/arbitrage_and_edges.md): prediction-market, crypto and put-call parity arbitrage explained, and why each gap usually covers a cost or a risk; what mid-horizon quant funds run.

Alpha research on ~100 large caps, 2010-2023: none of the 20 variants reached t > 2 in the claimed direction.
- 12-month momentum and 1-week reversal each came in at t ~ 1.95.
- The Kou et al. (arXiv 2409.06289) formulas are mostly noise; their 14-day momentum predicts the wrong way.
- Low-volatility has the wrong sign, which is survivorship bias at work.
- Top-3 momentum shows 33% CAGR, but its Sharpe equals equal-weight's, so the extra return is survivors plus concentration.
- Weekly reversal is destroyed by commissions ($11k on a $5k account).

## Current status and next steps
- **Pending decision:** make momentum + vol-managed the core, merge or cut the trend sleeve (risk parity is a tested candidate replacement: research/risk_parity.md), and replace the swing sleeve with something uncorrelated. The allocations in `config/settings.yaml` still hold all four sleeves (0.3/0.25/0.2/0.15, with 10% reserved for the LLM sleeve).
- **IBKR paper account:** connected 2026-10-01 via IB Gateway (paper, port 4002, account `DU…`; balance still the $1M default, to be reset to ~$5k; non-professional real-time US data subscribed). Ranked next steps and data needs: research/roadmap.md. The paper adapter is built and its what-if works against the account (2026-10-01). IBKR's what-if quoted $1.00 per order, i.e. **Fixed** pricing: switch the account to Tiered or backtest with `--plan fixed`. **Split (owner, 2026-10-01):** the ETF daily book forward-tests in `--mode shadow` only (started 2026-10-01, signal date 2026-09-30; run it every trading day after 16:10 ET or pre-market); IBKR paper is for strategies that need real data and real fills: ORB and stock momentum. Whole shares hurt momentum badly: the Aug-2026 top 10 at $5k is 43% misweighted (SNDK $1,740 and MU $1,065 get 0 shares; 15% at $10k), and those picks (SNDK, MU, WDC, STX, LITE, AMD...) duplicate the owner's semis-heavy long-term account. ORB already sizes in whole shares. Live stock picking without a real-time full-market feed (research/orb_experiments.md, Experiment 11): a proxy of IBKR's `SCAN_stVolumeVsAvg5min_DESC` scanner (50 rows at 9:35) contains the backtest's top-1 on 98% of days (Sharpe 0.80 vs 0.89 full market at 1c), but its own #1 is right only 44% of the time, so recompute exact relvol for the 50; pre-market lists fail (83%). `intraday.scanner_log capture` logs the real scanner each morning (needs Gateway up before 9:25 ET); `compare` scores it once Massive has the day. Longer opening ranges were tested and rejected (Experiment 12: 10/15/30/60 min all lose to 5 min overall; 10-15 min are better only after 2024). `intraday/orb_live.py` is the paper executor (built 2026-10-01, unit-tested, history step verified on real files; never yet run at 9:35); it is NOT in the scheduled jobs: the owner decides when it runs, what-if first. Place **no live orders** without an explicit go-ahead.
- **LLM fundamental scores (forward test, started 2026-10-01):** research/llm_fundamentals.md. Monthly: `data.massive download --dataset day`, then `llm.fundamentals export`, `run` (headless `claude -p`) or 20 subagents, then `check`. Claude scores the 200 largest companies from SEC quarterly XBRL + the latest 8-K earnings release + MD&A, with no prices. Pre-registered: PASS after 12 runs if the mean 1-month rank IC is > 0 (t > 1) and the top 20 beat the equal-weight universe; KILL if IC <= 0. Never back-fill past months.
- **Alpha extraction:** code is done and unit-tested with a mocked client, but it has **never run against the real API** (no key on this machine yet).
- **Paper-trading plan (from research/portfolio_mix.md):** daily book as the core, with the ORB baseline and QQQ noise-area momentum (at a reduced vol target) overlaid on the same margin account, total intraday gross under 4x. Needs a margin account with intraday leverage.
- **ORB:** best realistic setup is top-1, 1 ATR stop, stop-limit entry at the trigger, IBKR Pro Tiered ($5k: 12.2% CAGR, Sharpe 0.72, -22% max DD). That's roughly SPY-like Sharpe with no market correlation.
  - Pre-registered ideas (`intraday/orb_ideas.py`, 14 variants, pass = beats the baseline in both 2021-23 and 2024-26):
    - **Entry cutoff** (10:00/10:30/11:00) passed at every setting: Sharpe 0.83-0.85. It drops ~15-30 late trades a year.
    - **Relative volume** >= 5/8/12 passed: Sharpe 0.73/0.78/0.88. >= 3 changes nothing because the top-1 stock is always above 3.
    - **Failed badly:** trading with SPY's direction (0.41), breakeven stops (-0.15 to 0.68) and trailing stops (-1.77 to 0.45). Capping the runners destroys the edge.
    - No idea raised the win rate (~44%).
  - **Round 2 and large caps** (research/orb_experiments.md, Experiments 8-10): large-cap dollar-volume floors ($50M-$250M/day) cut slippage in bps (14 -> 5) but raise it in cents and kill the edge (Sharpe 0.70 -> -0.03 to 0.18). The overnight-gap catalyst proxy and the volatility-regime filter both fail the pre-registered rule; high-vol-only halves the drawdown at the same Sharpe.
  - **Inverted ORB** (research/orb_inverted.md): the exact mirror (fade at the breakout, target at ORB's stop, no stop) wins 53% vs 46% but is minus ORB trade for trade (verified): -26% CAGR, -79% DD at $5k. Fade with a 1 ATR stop -9.6%, fade bracket -11.9%, flipped direction (short a break of the low after an up candle) -0.2% at 0c, -5.9% with slippage. All fail. ORB's edge is a few huge winners (+13.9R MRNA); inverting turns them into huge losers. Exploratory fade brackets (`--brackets`, stop x target in {0.5,1,2} ATR, added after the fact): all 9 lose in both halves, -9% to -17% CAGR at 0c; expectancy is -0.02 to -0.06R whatever the ratio (2:0.5 wins 63% but needs 80%). The new bar walker reproduces orb.py's path results on all 19,934 trades.
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
