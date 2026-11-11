# Moves a disconnected RDP session onto the console, so it keeps a display.
# Java (IB Gateway) cannot start in a session with no display: every launch while RDP was
# disconnected died with HeadlessException, including IBC's daily 06:45 restart.
# Run by the SYSTEM task from install_rdp_console.ps1, from an admin-only copy of this file.
param([Parameter(Mandatory = $true)][string]$User)

$log = Join-Path $PSScriptRoot "rdp_to_console.log"
function Write-Log($message) {
    "$(Get-Date -Format s) $message" | Add-Content -Path $log
}

# A quick reconnect after a dropped connection leaves the session Active: nothing to move.
Start-Sleep -Seconds 3
$pattern = "\b$([regex]::Escape($User))\s+(\d+)\s+Disc\b"
$row = @(qwinsta.exe) | Where-Object { $_ -match $pattern } | Select-Object -First 1
if (-not $row) {
    Write-Log "no disconnected session for $User; nothing to do"
    exit 0
}
$null = $row -match $pattern
$id = $Matches[1]
$output = & tscon.exe $id /dest:console 2>&1
$code = $LASTEXITCODE
Write-Log "tscon $id /dest:console -> exit $code $output"
exit $code
