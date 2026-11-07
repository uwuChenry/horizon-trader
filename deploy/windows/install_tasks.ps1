# Registers every scheduled task for the current user on the OPS machine (HT_ROLE=ops in .env).
# Run once; re-running replaces them. Times are this PC's local clock, which must be Eastern.
#   07:30 Sun-Fri  logins       IB Gateway / Codex / Claude login check (Sunday: weekly IBKR re-login)
#   08:00 Mon-Fri  morning      Massive downloads + momentum orders (+ monthly LLM scores if due)
#   09:20 Mon-Fri  scanner      IBKR scanner lists at 09:25 / 09:35
#   09:24 Mon-Fri  observations read-only IBKR paper evidence (install_observer.ps1)
#   09:21 Mon-Fri  orb          ORB on IBKR paper: one bracket after 09:35 (IBKR manages the exit)
#   09:21 Mon-Fri  orb_alpaca   ORB on Alpaca paper (same pick), runs until ~16:10
#   09:25 Mon-Fri  noise        QQQ noise area, runs until ~16:05
#   14:30 Mon-Fri  canary       login check + one tiny codex exec call before the journal
#   15:00 Mon-Fri  journal      forecast journal + Alpaca competition follower
#   15:35 Mon-Fri  options_log  IBKR option-chain snapshot
#   18:00 Mon-Fri  evening      shadow + Alpaca daily book + competition sync + ORB fills (IBKR)
#   18:30 Mon-Fri  health       health report; "all OK" message on a clean day
#   at logon       dashboard    read-only dashboard on HT_DASHBOARD_HOST
# Tasks run only while this user is logged on (the Gateway needs a desktop anyway): use
# auto-logon on the mini and lock the screen. Windows are hidden, so closing a console can't
# kill a job. Failures alert via Discord/ntfy (ops/notify.py).
# Remove with: Unregister-ScheduledTask -TaskName "horizon-trader *" -Confirm:$false
$ErrorActionPreference = "Stop"
if ((Get-TimeZone).Id -ne "Eastern Standard Time") {
    throw "Set this PC's time zone to Eastern (US & Canada) first: the triggers use local time."
}
$dir = $PSScriptRoot
$weekdays = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
$sunToFri = @("Sunday") + $weekdays
$jobs = @(
    @{Name = "logins"; At = "07:30"; Days = $sunToFri; Hours = 1},
    @{Name = "morning"; At = "08:00"},
    @{Name = "scanner"; At = "09:20"},
    @{Name = "orb"; At = "09:21"; Hours = 7},
    @{Name = "orb_alpaca"; At = "09:21"; Hours = 8},
    @{Name = "noise"; At = "09:25"; Hours = 8},
    @{Name = "canary"; Script = "logins"; Args = "-Canary"; At = "14:30"; Hours = 1},
    @{Name = "journal"; At = "15:00"},
    @{Name = "options_log"; At = "15:35"},
    @{Name = "evening"; At = "18:00"},
    @{Name = "health"; At = "18:30"; Hours = 1}
)
foreach ($job in $jobs) {
    $hours = if ($job.Hours) { $job.Hours } else { 3 }
    $days = if ($job.Days) { $job.Days } else { $weekdays }
    $script = if ($job.Script) { $job.Script } else { $job.Name }
    $settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours $hours)
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$dir\$script.ps1`" $($job.Args)"
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $job.At
    Register-ScheduledTask -TaskName "horizon-trader $($job.Name)" -Action $action `
        -Trigger $trigger -Settings $settings -Force | Out-Null
    "registered horizon-trader $($job.Name) ($($job.At))"
}
# Dashboard: start at logon, no time limit, restart if it crashes.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$dir\dashboard.ps1`""
# DOMAIN\user: a bare user name fails ("parameter is incorrect") when the PC has the same name.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
Register-ScheduledTask -TaskName "horizon-trader dashboard" -Action $action `
    -Trigger $trigger -Settings $settings -Force | Out-Null
"registered horizon-trader dashboard (at logon)"
& "$dir\install_observer.ps1"
