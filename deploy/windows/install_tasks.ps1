# Registers the weekday jobs for the current user (run once; re-running replaces them):
# 08:00 morning (Massive downloads + momentum orders), 09:20 IBKR scanner log, 09:25 QQQ noise
# (runs until ~16:05), 15:00 forecast journal + Alpaca competition follower, 15:35 IBKR
# option-chain log, 18:00 evening. Windows are hidden, so closing a console can't kill a job.
# Remove with: Unregister-ScheduledTask -TaskName "horizon-trader *" -Confirm:$false
$dir = $PSScriptRoot
$days = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
foreach ($job in @(@{Name = "morning"; At = "08:00"}, @{Name = "scanner"; At = "09:20"},
                   @{Name = "noise"; At = "09:25"; Hours = 8}, @{Name = "journal"; At = "15:00"},
                   @{Name = "options_log"; At = "15:35"}, @{Name = "evening"; At = "18:00"})) {
    $hours = if ($job.Hours) { $job.Hours } else { 3 }
    $settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours $hours)
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$dir\$($job.Name).ps1`""
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $job.At
    Register-ScheduledTask -TaskName "horizon-trader $($job.Name)" -Action $action `
        -Trigger $trigger -Settings $settings -Force | Out-Null
    "registered horizon-trader $($job.Name) (weekdays $($job.At))"
}
