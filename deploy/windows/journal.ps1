# Weekday 15:30 job (Task Scheduler, New York time): the forecast journal. LLM analysts, debate
# and trader via `claude -p` (needs this user's Claude Code login), then code prices and scores
# a hypothetical book. Never places orders. Log: data/logs/<date>-journal.log
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$log = "data/logs/$(Get-Date -Format yyyy-MM-dd)-journal.log"
& uv run python -m horizon_trader.agents.journal run *>&1 | Out-File -Append -Encoding utf8 $log
