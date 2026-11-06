# Monthly Claude fundamental scores (research/llm_fundamentals): started in the background by
# the morning job after the Massive day download. Runs only when the current month has no run yet,
# so it fires on the month's first trading-day morning and catches up the next morning if the PC
# was off. Never back-dates: the as-of date is always today. Needs this user's Claude Code login.
# Log: data/logs/<date>-llm-fundamentals.log
# Steps now live in horizon_trader/ops/jobs.py.
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs llm_monthly
exit $LASTEXITCODE
