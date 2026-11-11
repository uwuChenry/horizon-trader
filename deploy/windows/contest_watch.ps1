# Weekday 09:40 job (Task Scheduler, New York time): the AI contest trader's watch. No LLM: every
# 15 minutes until 10 minutes before the close it books fills, re-places missing broker stops and
# closes positions whose option stop/target, exit date or contest end was reached
# (agents/contest_trader.py watch; IBKR NBBO for prices, client id 35; paper keys only, kill
# switch data/live/KILL). Log: data/logs/<date>-contest-watch.log. Steps live in ops/jobs.py.
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs contest_watch
$code = $LASTEXITCODE
# Task Scheduler has no OnFailure hook (systemd does): alert from here.
if ($code -ne 0) { & uv run python -m horizon_trader.ops.health --notify --failed contest_watch }
exit $code
