# Weekday 09:20 job (Task Scheduler, New York time): log IBKR's scanner lists at 09:25 and
# 09:35:05 (read-only, client id 11; exits ~09:36). Needs IB Gateway logged in (paper).
# Steps live in horizon_trader/ops/jobs.py. Log: data/logs/<date>-scanner.log
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs scanner
exit $LASTEXITCODE
