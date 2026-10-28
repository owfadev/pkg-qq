# Install/refresh the Windows Task Scheduler entries for the QQ listener and the
# unattended agent turn. Idempotent (-Force replaces existing tasks).
#
# Experimental: the core CLI runs on native Windows, but the unattended path
# assumes `claude` and the wrappers are reachable from the task's PATH. Verify on
# a real Windows host before calling it supported.
#
# Run in PowerShell from the repository root (no admin required for user tasks):
#   powershell -ExecutionPolicy Bypass -File connectors\qq-cli\windows\install-taskscheduler.ps1

param([switch]$DryRun)

$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$HomeDir = Join-Path $env:USERPROFILE '.qq-cli'
$Watch = Join-Path $Root 'connectors\qq-cli\scripts\qq-agent-watch.py'

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Error 'python not found on PATH; install the connector first'
    exit 1
}
$Python = $pythonCmd.Source
if (-not (Test-Path $Watch)) {
    Write-Error "watcher not found: $Watch"
    exit 1
}

$ListenName = 'owfa-qq-listen'
$AgentName = 'owfa-qq-agent'

$ListenAction = New-ScheduledTaskAction -Execute $Python `
    -Argument '-m qqcli listen --replace' -WorkingDirectory $Root
$ListenTrigger = New-ScheduledTaskTrigger -AtLogOn
$ListenSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$AgentAction = New-ScheduledTaskAction -Execute $Python `
    -Argument ('"' + $Watch + '"') -WorkingDirectory $Root
$AgentTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)
$AgentSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

if ($DryRun) {
    Write-Host "[dry-run] root=$Root python=$Python"
    Write-Host "[dry-run] would register $ListenName (AtLogOn) and $AgentName (every 1 minute)"
    exit 0
}

Register-ScheduledTask -TaskName $ListenName -Action $ListenAction `
    -Trigger $ListenTrigger -Settings $ListenSettings -Force | Out-Null
Register-ScheduledTask -TaskName $AgentName -Action $AgentAction `
    -Trigger $AgentTrigger -Settings $AgentSettings -Force | Out-Null

New-Item -ItemType Directory -Force -Path $HomeDir | Out-Null
$Marker = @{
    kind         = 'taskscheduler'
    root         = $Root
    python       = $Python
    installed_at = (Get-Date).ToString('o')
} | ConvertTo-Json -Compress
Set-Content -Path (Join-Path $HomeDir 'executor.json') -Value $Marker -Encoding UTF8

Write-Host "[ok] registered $ListenName and $AgentName"
