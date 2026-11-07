# Read-only paper evidence, weekdays 09:24–16:05 America/New_York.
# Steps now live in horizon_trader/ops/jobs.py.
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& "$repo/.venv/Scripts/python.exe" -m horizon_trader.ops.jobs observe
$code = $LASTEXITCODE
if ($code -ne 0) { & "$repo/.venv/Scripts/python.exe" -m horizon_trader.ops.health --notify --failed observe }
exit $code
