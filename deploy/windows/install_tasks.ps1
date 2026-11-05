# Registers the weekday jobs (08:00 morning, 15:30 forecast journal, 18:00 evening) for the current user (run once; re-running replaces them).
# Remove with: Unregister-ScheduledTask -TaskName "horizon-trader *" -Confirm:$false
$dir = $PSScriptRoot
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)
$days = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
foreach ($job in @(@{Name = "morning"; At = "08:00"}, @{Name = "journal"; At = "15:30"},
                   @{Name = "evening"; At = "18:00"})) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$dir\$($job.Name).ps1`""
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $job.At
    Register-ScheduledTask -TaskName "horizon-trader $($job.Name)" -Action $action `
        -Trigger $trigger -Settings $settings -Force | Out-Null
    "registered horizon-trader $($job.Name) (weekdays $($job.At))"
}
