# First-run bootstrap for the qq connector (native Windows).
# Installs the Python package, runs the offline doctor, and prints the human
# steps that cannot be automated. Never starts the listener or a task.
#
#   powershell -ExecutionPolicy Bypass -File connectors\qq-cli\scripts\bootstrap.ps1
#   ... -DryRun

param([switch]$DryRun)

$ErrorActionPreference = 'Stop'
$Here = Split-Path $PSScriptRoot -Parent      # connectors/qq-cli
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Error 'python not found on PATH; install Python 3.10+ first'
    exit 1
}
$Python = $PythonCmd.Source

if ($DryRun) {
    Write-Host "[dry-run] $Python -m pip install -e $Here"
    Write-Host "[dry-run] $Python -m qqcli doctor --offline"
} else {
    & $Python -m pip install -e $Here
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host ''
    & $Python -m qqcli doctor --offline
}

Write-Host @'

[bootstrap] remaining human steps (the agent can guide, but cannot do these):
  1. Create an official QQ Bot at https://q.qq.com, enable the C2C and group @
     scenarios, and copy the AppID.
  2. In your own terminal (needs a TTY):
       qq-cli secret set --app-id <AppID>
  3. Send one private message and one group @ to the bot, then:
       qq-cli requests
       qq-cli allow user|group <id> --label <name> --yes
  4. Refresh the token:      qq-cli ensure
  5. Start the listener:     qq-cli listen --detach
     or register the executor after confirmation:
       powershell -ExecutionPolicy Bypass -File connectors\qq-cli\windows\install-taskscheduler.ps1
'@
