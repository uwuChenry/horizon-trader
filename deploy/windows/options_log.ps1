# Weekday 15:35 job (Task Scheduler, New York time): snapshot IBKR option chains for the
# watchlist in config/options_log.yaml (read-only; needs IB Gateway logged in). Missed days
# can't be recovered: IBKR has no history for expired options. Log: data/logs/<date>-options.log
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$log = "data/logs/$(Get-Date -Format yyyy-MM-dd)-options.log"
& uv run python -m horizon_trader.datasources.ibkr_options_log capture *>&1 | Out-File -Append -Encoding utf8 $log
