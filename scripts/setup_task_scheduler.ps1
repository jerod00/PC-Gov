# Installs the Windows Task Scheduler job that runs the daily digest
# Monday-Friday at 6:30 AM (local machine time).
#
# IMPORTANT: Task Scheduler uses the Windows clock's local timezone, not
# "Central" specifically. If this machine isn't already set to Central Time,
# either change the machine's timezone or adjust -TriggerTime below to
# whatever local time corresponds to 6:30 AM Central.
#
# Run this from an elevated (Administrator) PowerShell prompt:
#   cd path\to\pc-gov-finder
#   .\scripts\setup_task_scheduler.ps1
#
# Re-running it updates the existing task in place.

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

# Prefer this project's own venv (where `pip install -r requirements.txt` was
# run) over whatever `python` happens to resolve to on PATH -- a scheduled
# task runs with no venv activated, so if PATH points at a different Python
# install than the one with our dependencies, every run fails silently with
# a missing-module error that nobody's watching for.
$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} else {
    $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) {
        throw "python.exe not found on PATH, and no venv at $VenvPython. Install Python 3.11+ and either create the venv (python -m venv venv; venv\Scripts\activate; pip install -r requirements.txt) or ensure 'python' works from a new terminal, then re-run this script."
    }
    Write-Warning "No venv found at $VenvPython -- using PATH's python ($PythonExe). Make sure this interpreter has requirements.txt installed, or the scheduled task will fail silently every run."
}

$TaskName   = "PC-Gov Opportunity Digest"
$ScriptPath = Join-Path $ProjectRoot "run_daily.py"

$Action  = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`"" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 6:30AM
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force `
    -Description "Runs PC-Gov's government contract opportunity finder and emails the ranked digest."

Write-Host "Task '$TaskName' installed: Mon-Fri at 6:30 AM, running $ScriptPath"
Write-Host "To test it immediately: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "To check its last result: Get-ScheduledTaskInfo -TaskName '$TaskName'"
