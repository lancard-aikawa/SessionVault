# Register the "SessionVault backup" task in Task Scheduler (docs/design.md section 6).
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1                every 30 minutes + at logon
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Minutes 15
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Unregister    remove the task
#
# Keep this file ASCII only. Windows PowerShell 5.1 reads a file without BOM as the ANSI code page
# (cp932 on Japanese Windows), so non-ASCII text breaks the parser. pwsh (7) is not always installed.
#
# The task runs scripts\sessionvault-launch.py with a base interpreter's pythonw.exe found by
# scripts\find-pythonw.ps1 (Python 3.10 or later; no .venv needed), so no console window opens.
# (.venv\Scripts\pythonw.exe made by uv 0.11 is a console launcher and opens one.) Check the result in the vault's log/ and the task's
# "Last Run Result" (0 = success, 1 = some files could not be read, or another run overlapped).
param(
    [int]$Minutes = 30,
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"
$name = "SessionVault backup"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "Removed: $name"
    return
}

$repo = Split-Path -Parent $PSScriptRoot
# A base interpreter's pythonw.exe (no .venv needed). find-pythonw.ps1 prints the reason when none is found.
$pythonw = & (Join-Path $PSScriptRoot "find-pythonw.ps1")
if ($LASTEXITCODE -ne 0 -or -not $pythonw) {
    throw "No Python to run the task (see the message above)."
}
$launcher = Join-Path $repo "scripts\sessionvault-launch.py"
$arguments = "`"$launcher`" backup"

$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $repo
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
# Run only while the user is logged on (no stored password).
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger @($every, $logon) -Settings $settings `
    -Principal $principal -Description "Copy Claude Code session history to the SessionVault vault ($repo)" -Force | Out-Null
Write-Host "Registered: $name (every $Minutes minutes + at logon)"
Write-Host "  $pythonw $arguments"
