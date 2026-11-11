# Weekday 13:30 job (Task Scheduler, New York time): the AI contest trader runs the Alpaca
# competition PAPER account by itself (agents/contest_trader.py; GPT-6 Astra via `codex exec`,
# needs this user's Codex/ChatGPT login). Code builds the briefing and option ladders, checks
# every order against hard limits, places stops; paper keys only, kill switch data/live/KILL.
# Log: data/logs/<date>-contest.log. Steps live in horizon_trader/ops/jobs.py.
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs contest
$code = $LASTEXITCODE
# Task Scheduler has no OnFailure hook (systemd does): alert from here.
if ($code -ne 0) { & uv run python -m horizon_trader.ops.health --notify --failed contest }
exit $code
