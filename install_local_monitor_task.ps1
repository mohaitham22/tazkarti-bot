<#
    Register the always-on local Tazkarti watcher as a Windows scheduled task.

    Run this once, from a normal (non-admin) PowerShell:

        powershell -ExecutionPolicy Bypass -File .\install_local_monitor_task.ps1

    Why Task Scheduler and not a service (NSSM):
      * Nothing to install, and the task is inspectable from taskschd.msc.
      * The two things NSSM would buy us -- automatic restart and log
        rotation -- the script now does itself (it relaunches Chromium on
        any failure, and rotates its own log), so NSSM's remaining
        advantage is only "starts before anyone logs in".
      * That advantage costs real money here: a service runs as SYSTEM,
        and Playwright's Chromium lives in the USER profile at
        %LOCALAPPDATA%\ms-playwright, so SYSTEM cannot find it without
        extra path plumbing. Running the service as this account instead
        means storing a Microsoft-account password, which is worse.

    So: run as the logged-on user, start at logon, and re-check every
    minute. See the header comments on the triggers below.

    To remove:  Unregister-ScheduledTask -TaskName "Tazkarti Local Monitor" -Confirm:$false
#>

$ErrorActionPreference = "Stop"

$TaskName = "Tazkarti Local Monitor"
$Repo     = "c:\Users\mooda\OneDrive\Desktop\tazkarti"
$Script   = "alahly_ticket_monitor.py"

# pythonw.exe, not python.exe: this task runs in the interactive session,
# and python.exe would pop a console window at every logon and at every
# watchdog restart. Everything the script prints goes to
# %LOCALAPPDATA%\tazkarti-monitor\monitor.log regardless.
$PythonW  = "C:\Users\mooda\anaconda3\pythonw.exe"

foreach ($p in @($PythonW, (Join-Path $Repo $Script))) {
    if (-not (Test-Path $p)) { throw "Not found: $p" }
}

$action = New-ScheduledTaskAction -Execute $PythonW `
                                  -Argument "-u $Script" `
                                  -WorkingDirectory $Repo

# Trigger 1 -- start when this user logs on, which is what makes it come
# back after a reboot.
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

# Trigger 2 -- the watchdog. Fires every minute, forever. Combined with
# MultipleInstances=IgnoreNew below it is a no-op while the monitor is
# alive, and a restart within ~60s of it dying for any reason the script
# could not catch itself: an OOM kill, a Python-level crash, a stray
# taskkill. This is the piece that replaces NSSM's auto-restart.
#
# One minute rather than five because queue position on this site is
# assigned by arrival time, so a restart gap is alert latency, and alert
# latency is the whole reason this local runner exists. Checking a
# not-running condition once a minute costs nothing measurable.
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
                                     -RepetitionInterval (New-TimeSpan -Minutes 1) `
                                     -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# Interactive = "Run only when user is logged on". No stored password,
# and the task inherits this account's environment -- which is where
# Playwright's browsers actually are.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
                                        -LogonType Interactive `
                                        -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Output "Removing the existing '$TaskName' task first."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName `
    -Action $action `
    -Trigger @($atLogon, $watchdog) `
    -Settings $settings `
    -Principal $principal `
    -Description "Polls Tazkarti every 30s for Al Ahly ticket availability and alerts via Telegram. Fast signal; the GitHub Actions job is the slow one. Log: %LOCALAPPDATA%\tazkarti-monitor\monitor.log" | Out-Null

Write-Output "Registered '$TaskName'."
Get-ScheduledTask -TaskName $TaskName |
    Select-Object TaskName, State, @{n='Triggers';e={$_.Triggers.Count}} |
    Format-Table -AutoSize
