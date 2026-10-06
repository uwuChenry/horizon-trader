# Weekday morning job (Task Scheduler, 08:00 New York time; this PC's clock is Eastern).
# 1. Download yesterday's Massive day + minute files (ORB history, scanner scoring).
# 2. Score past scanner logs against the true ORB pick.
# 3. Capture today's IBKR scanner lists at 9:25 and 9:35 (read-only; exits ~9:36).
# Needs IB Gateway running and logged in (paper). Log: data/logs/<date>-morning.log
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$log = "data/logs/$(Get-Date -Format yyyy-MM-dd)-morning.log"
function Step($name, [string[]]$cmd) {
    "=== $(Get-Date -Format HH:mm:ss) $name" | Out-File -Append -Encoding utf8 $log
    & uv run python -m @cmd *>&1 | Out-File -Append -Encoding utf8 $log
}
Step "massive day" @("horizon_trader.datasources.massive", "download", "--dataset", "day")
Step "massive minute" @("horizon_trader.datasources.massive", "download", "--dataset", "minute")
Step "scanner compare" @("horizon_trader.intraday.scanner_log", "compare")
Step "scanner capture" @("horizon_trader.intraday.scanner_log", "capture")
"=== $(Get-Date -Format HH:mm:ss) done" | Out-File -Append -Encoding utf8 $log
