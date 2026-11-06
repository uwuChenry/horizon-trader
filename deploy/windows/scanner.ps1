# Weekday 09:20 job (Task Scheduler, New York time): log IBKR's scanner lists at 09:25 and
# 09:35:05 (read-only, client id 11; exits ~09:36). Was the last step of the 08:00 morning job,
# which then sat waiting 85 minutes; on its own it starts 5 minutes before it's needed.
# Needs IB Gateway logged in (paper). Log: data/logs/<date>-scanner.log
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$log = "data/logs/$(Get-Date -Format yyyy-MM-dd)-scanner.log"
& uv run python -m horizon_trader.intraday.scanner_log capture *>&1 | Out-File -Append -Encoding utf8 $log
