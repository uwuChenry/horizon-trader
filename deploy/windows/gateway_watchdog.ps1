# IB Gateway watchdog (ops/gateway_watchdog.py): every 5 minutes Sun-Fri 07:05-23:30, a live API
# probe; two failures in a row -> kill the Gateway's java.exe, restart the "IBC Gateway (paper)"
# task, urgent alert. The Python module writes data/logs/<date>-watchdog.log only when something
# is wrong; this wrapper adds its output there only if the module itself fails.
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$out = & uv run python -m horizon_trader.ops.gateway_watchdog *>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
    "=== $(Get-Date -Format HH:mm:ss) watchdog exit $LASTEXITCODE`n$out" |
        Out-File -Append -Encoding utf8 "data/logs/$(Get-Date -Format yyyy-MM-dd)-watchdog.log"
}
exit $LASTEXITCODE
