# Weekday morning job (Task Scheduler, 08:00 New York time; this PC's clock is Eastern).
# 1. Download yesterday's Massive day file.
# 2. Large-cap momentum on its Alpaca PAPER account (execution/momentum_book.py): yesterday's
#    close (the month-end close on a formation day) -> market orders queued for today's open.
#    Refuses once the market is open, so a late start (PC off at 08:00) skips the day.
# 3. Download yesterday's minute file (ORB history, scanner scoring, QQQ noise bands).
# 4. Score past scanner logs against the true ORB pick.
# (Today's scanner capture is its own 09:20 job, scanner.ps1.)
# Also starts llm_monthly.ps1 in the background after the day download (it exits at once
# unless this month's LLM fundamental scores are still missing).
# Log: data/logs/<date>-morning.log
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
Step "momentum (Alpaca paper)" @("horizon_trader.execution.momentum_book", "run")
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList `
    "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\llm_monthly.ps1`""
Step "massive minute" @("horizon_trader.datasources.massive", "download", "--dataset", "minute")
Step "scanner compare" @("horizon_trader.intraday.scanner_log", "compare")
"=== $(Get-Date -Format HH:mm:ss) done" | Out-File -Append -Encoding utf8 $log
