# Weekday evening job (Task Scheduler, 18:00 New York time): forward test of the ETF book in
# our own simulator (run_daily --mode shadow). No IBKR. Log: data/logs/<date>-evening.log
# Then the same book on its own Alpaca paper account (run_daily --mode alpaca: fractional
# orders queued for the next open; skipped until ALPACA_DAILY_BOOK_* keys are in .env).
# Then a sync-only run of the Alpaca competition follower (market closed: it books the day's
# fills and records closing equity, and sends nothing). Log: data/logs/<date>-competition.log
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$day = Get-Date -Format yyyy-MM-dd
& uv run python -m horizon_trader.run_daily --mode shadow *>&1 |
    Out-File -Append -Encoding utf8 "data/logs/$day-evening.log"
if (Select-String -Path ".env" -Pattern "^ALPACA_DAILY_BOOK_API_KEY=PK" -Quiet) {
    & uv run python -m horizon_trader.run_daily --mode alpaca *>&1 |
        Out-File -Append -Encoding utf8 "data/logs/$day-evening.log"
}
& uv run python -m horizon_trader.agents.competition run *>&1 |
    Out-File -Append -Encoding utf8 "data/logs/$day-competition.log"
