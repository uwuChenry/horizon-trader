# Weekday 15:00 job (Task Scheduler, New York time): the forecast journal. LLM analysts, debate
# and trader on GPT-6.1 Sol via `codex exec` (needs this user's Codex/ChatGPT login), then code prices and scores
# a hypothetical book. The journal itself never places orders. Log: data/logs/<date>-journal.log
#
# The AI competition account no longer follows the journal: the contest trader (contest.ps1,
# 13:30) decides for itself and may read the journal's latest view as one input.
# Steps now live in horizon_trader/ops/jobs.py.
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs journal
$code = $LASTEXITCODE
# Task Scheduler has no OnFailure hook (systemd does): alert from here.
if ($code -ne 0) { & uv run python -m horizon_trader.ops.health --notify --failed journal }
exit $code
