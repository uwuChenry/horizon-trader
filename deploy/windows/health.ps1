# Weekday 18:30 health report (ops/health.py): alerts on stale ledgers, missed downloads or
# snapshots, disk space, overdue LLM month; on a clean day sends one short "all OK" message, so a
# silent channel means the alerting itself is broken. Log: data/logs/<date>-health.log
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$log = "data/logs/$(Get-Date -Format yyyy-MM-dd)-health.log"
& uv run python -m horizon_trader.ops.health --notify --daily *>&1 | Out-File -Append -Encoding utf8 $log
exit $LASTEXITCODE
