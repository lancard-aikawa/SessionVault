# Register the "SessionVault backup" task in Task Scheduler (docs/design.md section 6).
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1                every 30 minutes + at logon
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Minutes 15
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Unregister    remove the task
#
# Keep this file ASCII only. Windows PowerShell 5.1 reads a file without BOM as the ANSI code page
# (cp932 on Japanese Windows), so non-ASCII text breaks the parser. pwsh (7) is not always installed.
#
# The task runs scripts\sessionvault-launch.py with the base interpreter's pythonw.exe (the "home" in
# .venv\pyvenv.cfg), so no console window opens. (.venv\Scripts\pythonw.exe made by uv 0.11 is a
# console launcher and opens one.) Check the result in the vault's log/ and the task's
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
$cfg = Join-Path $repo ".venv\pyvenv.cfg"
if (-not (Test-Path $cfg)) {
    throw "$cfg not found. Run 'uv sync' in the repository first."
}
$homeLine = Get-Content $cfg -Encoding utf8 | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1
$pythonw = if ($homeLine) { Join-Path ($homeLine -replace '^\s*home\s*=\s*', '').Trim() "pythonw.exe" } else { "" }
if (-not $pythonw -or -not (Test-Path $pythonw)) {
    throw "pythonw.exe of the base Python not found (the 'home' in $cfg)."
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
