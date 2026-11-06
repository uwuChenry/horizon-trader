# Weekday morning job (Task Scheduler, 08:00 New York time; this PC's clock is Eastern).
# 1. Download yesterday's Massive day + minute files (ORB history, scanner scoring).
# 2. Score past scanner logs against the true ORB pick.
# 3. Capture today's IBKR scanner lists at 9:25 and 9:35 (read-only; exits ~9:36).
# Also starts the llm_monthly job in the background after the day download (it exits at once
# unless this month's Claude fundamental scores are still missing).
# Needs IB Gateway running and logged in (paper). Log: data/logs/<date>-morning.log
# Steps now live in horizon_trader/ops/jobs.py.
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs morning
exit $LASTEXITCODE
