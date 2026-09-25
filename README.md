# horizon-trader

A Python trading system for US stocks and ETFs, traded through IBKR, focused on swing (days) and position (weeks to months) horizons. Each strategy ("sleeve") outputs **target weights**. The portfolio layer nets the sleeves into one book and applies risk limits. Execution trades only the difference between current and target positions.

```
data ─► sleeves (swing / position / llm / papers) ─► portfolio + risk ─► execution (IBKR)
```

## Setup (same on Windows, Ubuntu, and ARM64)

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

On a server, use `uv sync --no-dev` to keep the install lean.

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
| `research/` | notebooks and replications of published papers |
| `deploy/` | Dockerfile, compose placeholder, systemd timer |

State (Parquet and SQLite files) lives in `./data`, or in `$HT_DATA_DIR` if set. It is git-ignored.

## Roadmap

1. ~~Data store and universe~~
2. ~~Position (momentum rotation) and swing (mean reversion) sleeves~~
3. ~~Daily backtester with IBKR costs~~
4. IBKR paper execution (`ib_async`)
5. LLM sleeve and first paper replication
6. Survivorship-free data, ML models, small live capital
