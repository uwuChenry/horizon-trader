# horizon-trader

A Python trading system for US stocks and ETFs, traded through IBKR, focused on swing (days) and position (weeks to months) horizons. Each strategy ("sleeve") outputs **target weights**. The portfolio layer nets the sleeves into one book and applies risk limits. Execution trades only the difference between current and target positions.

```
data ─► sleeves (swing / position / llm / papers) ─► portfolio + risk ─► execution (IBKR)
```

## Setup (same on Windows, Ubuntu, and ARM64)

For a shared Windows/Ubuntu checkout on `D:\github`, see [dual-boot setup](docs/dual-boot.md).

Install [uv](https://docs.astral.sh/uv/):

- Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- Linux:   `curl -LsSf https://astral.sh/uv/install.sh | sh`

Then:

```bash
uv sync                      # creates .venv with the pinned Python 3.12 + locked deps (incl. dev)
uv sync --group research     # + vectorbt, lightgbm, jupyter for research
cp .env.example .env         # fill in IBKR + Anthropic settings
uv run pytest
uv run python -m horizon_trader.run_daily --dry-run
uv run python -m horizon_trader.backtest.run --start 2008-01-01   # add --refresh / --plan tiered
uv run python -m horizon_trader.backtest.robustness               # param grids, walk-forward, correlations
uv run python -m horizon_trader.execution.ibkr                    # read-only IBKR connection check
```

## Alpha research: papers to formulas to evidence

```bash
uv run python -m horizon_trader.alphas.cli extract https://arxiv.org/pdf/2409.06289   # needs ANTHROPIC_API_KEY
uv run python -m horizon_trader.alphas.cli evaluate research/alphas/classics.yaml      # rank-IC report
uv run python -m horizon_trader.alphas.cli backtest research/alphas/classics.yaml mom_12_1
```

- **Formula language** (`alphas/dsl.py`): parsed with `ast`, never `eval`'d. Every operator is causal, so formulas written by an LLM can't run arbitrary code and can't look ahead.
- **Libraries** (`research/alphas/*.yaml`): each formula comes with its source and the direction the paper claims, recorded before testing.
- **Holdout:** 2024 onward is hidden unless you pass `--holdout`.
- **Universe** (`config/universes/us_large_cap.yaml`): today's large caps, which is survivorship-biased. Judge alphas against the equal-weight row, not SPY.

On a server, use `uv sync --no-dev` to keep the install lean.

## Dashboard and research

```bash
cd web && npm install && npm run build     # once (needs Node 20+), and after frontend changes
uv run python -m horizon_trader.dashboard  # http://127.0.0.1:8501
```

A read-only web app (FastAPI + React): an overview of forward tests and job health, the research
catalog, every saved backtest (trades, costs, holdings, in- vs out-of-sample), live/paper ledgers,
the ORB day viewer and the forecast journal. For frontend work, run `npm run dev` in `web/` (port 5173, proxies the API).

Every study lives in its own folder, `research/<slug>/`, with a `README.md` (verdict first) and a
`result.json` (status, verdict, tags, period, artifacts). [research/README.md](research/README.md)
is the generated index; regenerate it with `uv run python -m horizon_trader.results.index`.
See [the results format guide](docs/results.md).

## Forecast journal (LLM agents, forward test)

```bash
uv run python -m horizon_trader.agents.journal run   # weekdays ~15:30 ET; needs a Claude Code login
```

Each trading day an LLM team (market, news and earnings analysts, a bull/bear debate, a trader)
writes down SPY/QQQ calls and option-trade specs. Code prices them from live quotes, opens an
opposite "mirror" trade as the control, and scores everything after 5 and 20 days. It never
places an order. Rules: [research/forecast_journal/protocol.md](research/forecast_journal/protocol.md).

## Layout

| Path | Purpose |
|---|---|
| `config/settings.yaml` | universe, sleeve allocations, risk limits, execution settings |
| `src/horizon_trader/data` | price, fundamental, and text sources; Parquet store |
| `src/horizon_trader/features`, `models` | feature panels; rules → ridge → LightGBM; walk-forward CV |
| `src/horizon_trader/sleeves` | strategies implementing the `Sleeve` protocol (register them in `SLEEVE_TYPES`) |
| `src/horizon_trader/portfolio` | net sleeve weights, apply risk caps |
| `src/horizon_trader/execution` | `Broker` protocol, paper simulator, rebalance → orders |
| `src/horizon_trader/backtest` | vectorized screens and the daily simulator (reuses the live code) |
| `src/horizon_trader/llm` | LLM scoring with timestamped outputs (forward-test only) |
| `research/` | one folder per study: README, result.json, protocol, evidence |
| `src/horizon_trader/dashboard`, `web/` | dashboard API (FastAPI) and frontend (React) |
| `deploy/` | Dockerfile, compose placeholder, systemd timer |

State (Parquet and SQLite files) lives in `./data`, or in `$HT_DATA_DIR` if set. It is git-ignored.

## Roadmap

1. ~~Data store and universe~~
2. ~~Position (momentum rotation) and swing (mean reversion) sleeves~~
3. ~~Daily backtester with IBKR costs~~
4. IBKR paper execution (`ib_async`)
5. LLM sleeve and first paper replication
6. Survivorship-free data, ML models, small live capital
