# register_healthcheck.ps1
# Registers the Anchor Health Check as a Windows Scheduled Task that runs
# every morning at 5:00 AM, regardless of whether the user is logged in.
#
# Run once, from PowerShell, in the Anchor PSU directory:
#     powershell -ExecutionPolicy Bypass -File .\register_healthcheck.ps1
#
# To remove the task later:
#     Unregister-ScheduledTask -TaskName "Anchor Health Check" -Confirm:$false

$ErrorActionPreference = "Stop"

$TaskName = "Anchor Health Check"
$AnchorDir = $PSScriptRoot
$Script = Join-Path $AnchorDir "anchor_healthcheck.py"

if (-not (Test-Path $Script)) {
    Write-Error "anchor_healthcheck.py not found at $Script"
    exit 1
}

# Find pythonw.exe (no console window flash). Fall back to python.exe.
$python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    Write-Error "Could not find pythonw.exe or python.exe on PATH."
    exit 1
}

Write-Host "Anchor directory : $AnchorDir"
Write-Host "Python exe       : $python"
Write-Host "Script           : $Script"
Write-Host ""

# Build the action: run pythonw on the script, with PSU dir as the working dir
$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$Script`"" `
    -WorkingDirectory $AnchorDir

# Daily at 5:00 AM
$trigger = New-ScheduledTaskTrigger -Daily -At 5:00AM

# Run as the current user, only when network is available, don't wake from sleep,
# allow the task to run if the scheduled time was missed (e.g., laptop was asleep).
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# Remove any existing task with this name first
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Removing existing scheduled task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Daily 5:00 AM health check for Anchor (file integrity, server boot, endpoints, logging). See health_reports/." | Out-Null

Write-Host "Scheduled task '$TaskName' registered."
Write-Host ""
Write-Host "Verify with:  Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "Run now with: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove with:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
