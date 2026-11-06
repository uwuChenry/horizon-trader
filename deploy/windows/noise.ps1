# Weekday 09:25 job (Task Scheduler, New York time): QQQ noise-area intraday momentum on its
# own Alpaca PAPER account (intraday/noise_live.py; ALPACA_QQQ_NOISE_* paper keys). Checks at
# 10:00, 10:30, ..., 15:30, closes any position market-on-close and exits ~16:05.
# Prices from IB Gateway (read-only, client id 41), Alpaca IEX as the fallback. Needs the
# morning job's Massive minute download (yesterday) or it doesn't trade.
# Kill switch: data/live/KILL blocks new entries. Log: data/logs/<date>-noise.log
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$log = "data/logs/$(Get-Date -Format yyyy-MM-dd)-noise.log"
& uv run python -m horizon_trader.intraday.noise_live run *>&1 | Out-File -Append -Encoding utf8 $log
