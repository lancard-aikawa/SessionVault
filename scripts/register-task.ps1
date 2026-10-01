# タスクスケジューラに「SessionVault backup」を登録する（docs/design.md §6）
#   pwsh -File scripts\register-task.ps1                 30 分ごと + ログオン時
#   pwsh -File scripts\register-task.ps1 -Minutes 15
#   pwsh -File scripts\register-task.ps1 -Unregister     消す
# リポジトリの .venv の pythonw.exe で動かすので、コンソールの窓は開かない。結果は保管庫の log/ と、
# タスクの「前回の実行結果」（0 = 成功、1 = 読めないファイルがあった・別の実行と重なった）で見る。
param(
    [int]$Minutes = 30,
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"
$name = "SessionVault backup"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "消しました: $name"
    return
}

$repo = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    throw "$pythonw がありません。先にリポジトリで uv sync を実行してください"
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m sessionvault backup" -WorkingDirectory $repo
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
# ログオンしているときだけ動かす（パスワードを預けない）
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger @($every, $logon) -Settings $settings `
    -Principal $principal -Description "Claude Code のセッション履歴を SessionVault の保管庫へ写す（$repo）" -Force | Out-Null
Write-Host "登録しました: $name（$Minutes 分ごと + ログオン時）"
Write-Host "  $pythonw -m sessionvault backup"
