# Login checks (ops/logins.py): IB Gateway, Codex and Claude logins; with -Canary also one tiny
# `codex exec` call. Urgent Discord/ntfy alert on any failure. Scheduled 07:30 Sun-Fri and
# 14:30 Mon-Fri (-Canary). Log: data/logs/<date>-logins.log
param([switch]$Canary)
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$log = "data/logs/$(Get-Date -Format yyyy-MM-dd)-logins.log"
$extra = if ($Canary) { @("--canary") } else { @() }
"=== $(Get-Date -Format HH:mm:ss) logins $extra" | Out-File -Append -Encoding utf8 $log
& uv run python -m horizon_trader.ops.logins --notify @extra *>&1 | Out-File -Append -Encoding utf8 $log
exit $LASTEXITCODE
