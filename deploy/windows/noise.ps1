# Weekday 09:25 job (Task Scheduler, New York time): QQQ noise-area intraday momentum on its
# own Alpaca PAPER account (intraday/noise_live.py; ALPACA_QQQ_NOISE_* paper keys). Checks at
# 10:00, 10:30, ..., 15:30, closes any position market-on-close and exits ~16:05.
# Prices from IB Gateway (read-only, client id 41), Alpaca IEX as the fallback. Needs the
# morning job's Massive minute download (yesterday) or it doesn't trade.
# Kill switch: data/live/KILL blocks new entries. Steps live in horizon_trader/ops/jobs.py.
# Log: data/logs/<date>-noise.log
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs noise
$code = $LASTEXITCODE
# Task Scheduler has no OnFailure hook (systemd does): alert from here.
if ($code -ne 0) { & uv run python -m horizon_trader.ops.health --notify --failed noise }
exit $code
