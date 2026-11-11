# Registers the SYSTEM task that moves a disconnected RDP session onto the console, so
# IB Gateway can still start (see rdp_to_console.ps1). Run once from an elevated PowerShell;
# re-running replaces it. The script is copied under Program Files so the SYSTEM task never
# runs a file a normal user can edit. The log is rdp_to_console.log next to that copy.
# Side effect: after an RDP disconnect the desktop is shown unlocked on the attached monitor.
# Remove with: Unregister-ScheduledTask -TaskName "horizon-trader rdp_to_console" -Confirm:$false
$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this from an elevated (Administrator) PowerShell."
}

$target = Join-Path $env:ProgramFiles "horizon-trader"
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Force (Join-Path $PSScriptRoot "rdp_to_console.ps1") $target
$script = Join-Path $target "rdp_to_console.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -User $env:USERNAME"
# No cmdlet builds this trigger. StateChange 4 = TASK_REMOTE_DISCONNECT.
$class = Get-CimClass -Namespace "Root/Microsoft/Windows/TaskScheduler" `
    -ClassName "MSFT_TaskSessionStateChangeTrigger"
$trigger = New-CimInstance -CimClass $class -ClientOnly
$trigger.StateChange = 4
$trigger.Enabled = $true
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
Register-ScheduledTask -TaskName "horizon-trader rdp_to_console" -Action $action `
    -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
"registered horizon-trader rdp_to_console (on RDP disconnect, user $env:USERNAME)"
