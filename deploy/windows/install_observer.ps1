# Dedicated task: does not replace the existing downloader/shadow jobs.
$ErrorActionPreference = "Stop"
if ((Get-TimeZone).Id -ne "Eastern Standard Time") {
    throw "This schedule requires the Windows Eastern time zone; configure an ET trigger first."
}
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSScriptRoot\observe.ps1`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "09:24"
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 7) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2)
Register-ScheduledTask -TaskName "horizon-trader observations" -Action $action `
    -Trigger $trigger -Settings $settings -Description "Read-only IBKR paper scanner, quotes and execution evidence" -Force | Out-Null
Get-ScheduledTask -TaskName "horizon-trader observations" | Select-Object TaskName,State
