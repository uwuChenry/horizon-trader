# Weekday evening job (Task Scheduler, 18:00 New York time): forward test of the ETF book in
# our own simulator (run_daily --mode shadow). No IBKR. Log: data/logs/<date>-evening.log
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$log = "data/logs/$(Get-Date -Format yyyy-MM-dd)-evening.log"
& uv run python -m horizon_trader.run_daily --mode shadow *>&1 | Out-File -Append -Encoding utf8 $log
