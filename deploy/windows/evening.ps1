# Weekday evening job (Task Scheduler, 18:00 New York time): forward test of the ETF book in
# our own simulator (run_daily --mode shadow). No IBKR. Log: data/logs/<date>-evening.log
# Then the same book on its own Alpaca paper account (run_daily --mode alpaca: fractional
# orders queued for the next open; skipped until ALPACA_DAILY_BOOK_* keys are in .env).
# Then a sync-only run of the Alpaca competition follower (market closed: it books the day's
# fills and records closing equity, and sends nothing). Log: data/logs/<date>-competition.log
# Steps now live in horizon_trader/ops/jobs.py.
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs evening
$code = $LASTEXITCODE
# Task Scheduler has no OnFailure hook (systemd does): alert from here.
if ($code -ne 0) { & uv run python -m horizon_trader.ops.health --notify --failed evening }
exit $code
