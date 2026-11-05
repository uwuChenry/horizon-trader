# Weekday 15:00 job (Task Scheduler, New York time): the forecast journal. LLM analysts, debate
# and trader via `claude -p` (needs this user's Claude Code login), then code prices and scores
# a hypothetical book. The journal itself never places orders. Log: data/logs/<date>-journal.log
#
# Then the Alpaca competition follower executes the journal's new ideas in the AI competition
# PAPER account (agents/competition.py; paper keys only, kill switch data/live/KILL). It runs
# even if the journal failed, so planned closes (expiry eve, contest end) still happen.
# Log: data/logs/<date>-competition.log
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$day = Get-Date -Format yyyy-MM-dd
& uv run python -m horizon_trader.agents.journal run *>&1 |
    Out-File -Append -Encoding utf8 "data/logs/$day-journal.log"
& uv run python -m horizon_trader.agents.competition run *>&1 |
    Out-File -Append -Encoding utf8 "data/logs/$day-competition.log"
