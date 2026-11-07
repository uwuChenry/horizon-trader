# Weekday 15:35 job (Task Scheduler, New York time): snapshot IBKR option chains for the
# watchlist in config/options_log.yaml (read-only; needs IB Gateway logged in). Missed days
# can't be recovered: IBKR has no history for expired options. Log: data/logs/<date>-options.log
# Steps now live in horizon_trader/ops/jobs.py.
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs options_log
$code = $LASTEXITCODE
# Task Scheduler has no OnFailure hook (systemd does): alert from here.
if ($code -ne 0) { & uv run python -m horizon_trader.ops.health --notify --failed options_log }
exit $code
