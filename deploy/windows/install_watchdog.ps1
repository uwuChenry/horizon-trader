# Registers "horizon-trader gateway_watchdog": every 5 minutes, Sun-Fri 07:05-23:30 (local time =
# Eastern). It skips IBC's 06:45 restart and the overnight IBKR server reset. Re-running replaces it.
$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
$days = "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At "07:05"
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At "07:05" `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Hours 16 -Minutes 25)).Repetition
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$dir\gateway_watchdog.ps1`""
Register-ScheduledTask -TaskName "horizon-trader gateway_watchdog" -Action $action `
    -Trigger $trigger -Settings $settings -Force | Out-Null
"registered horizon-trader gateway_watchdog (every 5 min, Sun-Fri 07:05-23:30)"
