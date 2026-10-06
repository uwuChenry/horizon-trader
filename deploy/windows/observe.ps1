# Read-only paper evidence, weekdays 09:24–16:05 America/New_York.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location -LiteralPath $repo
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$log = Join-Path $repo ("data/logs/" + (Get-Date -Format yyyy-MM-dd) + "-observe.log")
$since = (Get-Date).AddDays(-7).ToString("yyyy-MM-dd")
$until = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
foreach ($dataset in @("day", "minute")) {
    & "$repo/.venv/Scripts/python.exe" -m horizon_trader.datasources.massive download `
        --dataset $dataset --start $since --end $until *>> $log
    if ($LASTEXITCODE -ne 0) {
        "Recent $dataset download failed; observer will log stale history." | Out-File -Append $log
    }
}
& "$repo/.venv/Scripts/python.exe" -m horizon_trader.execution.observe --session *>> $log
exit $LASTEXITCODE
