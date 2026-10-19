<#
.SYNOPSIS
  Rotate Anchor's service token (run ELEVATED).

.DESCRIPTION
  Anchor's API is guarded by one shared secret, ANCHOR_TOKEN, held in the NSSM service's environment
  (HKLM:\SYSTEM\CurrentControlSet\Services\anchor\Parameters, AppEnvironmentExtra). Every browser and device that
  talks to Anchor presents it. Rotating = minting a fresh random token, writing it into the service environment
  (every other pair preserved), restarting the service, and putting the NEW token on your clipboard so each
  browser can be given it once when the page asks. The token is never printed to the console or a log.

  The restart is a STOP, a wait for the port to be free, then a START, then a check that the service answers —
  never `nssm restart`, which on 2026-09-28 stopped the service and left it stopped (the new process could not
  bind while the old one drained, exited clean, and nothing came back).

.PARAMETER Svc
  The service name (default: anchor).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\tools\rotate_token.ps1
#>
param([string]$Svc = 'anchor', [int]$Port = 8777)

$ErrorActionPreference = 'Stop'
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Run this from an ELEVATED PowerShell (the service environment is under HKLM)." -ForegroundColor Yellow
    exit 2
}
$nssm = if (Test-Path 'C:\Tools\nssm\nssm.exe') { 'C:\Tools\nssm\nssm.exe' } else { (Get-Command nssm -ErrorAction Stop).Source }

# the current pairs, read from the registry (a clean String[]), never `nssm get` (UTF-16 mis-decodes)
$key = "HKLM:\SYSTEM\CurrentControlSet\Services\$Svc\Parameters"
$val = (Get-ItemProperty -Path $key -Name AppEnvironmentExtra -ErrorAction SilentlyContinue).AppEnvironmentExtra
$map = [ordered]@{}
foreach ($line in @($val)) {
    $line = "$line".Trim(); if (-not $line) { continue }
    $i = $line.IndexOf('='); if ($i -lt 1) { continue }
    $map[$line.Substring(0, $i)] = $line.Substring($i + 1)
}
if (-not $map.Contains('ANCHOR_TOKEN')) {
    Write-Host "No ANCHOR_TOKEN is set on the $Svc service (auth is off); nothing to rotate." -ForegroundColor Yellow
    exit 1
}

# a fresh token: 32 random bytes, url-safe base64, no padding
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$new = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
$map['ANCHOR_TOKEN'] = $new

$pairs = @(); foreach ($k in $map.Keys) { $pairs += ("{0}={1}" -f $k, $map[$k]) }
& $nssm set $Svc AppEnvironmentExtra @pairs | Out-Null
Set-Clipboard -Value $new
Write-Host "The new token is written into the service and is on your CLIPBOARD (never printed here)." -ForegroundColor Green

# a real restart: stop, wait for the port, start, verify
Write-Host "Stopping $Svc..." -ForegroundColor DarkGray
try { Stop-Service -Name $Svc -Force -ErrorAction Stop } catch { Write-Host "  (stop: $($_.Exception.Message))" -ForegroundColor DarkGray }
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    $svc = Get-Service -Name $Svc
    $busy = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($svc.Status -eq 'Stopped' -and -not $busy) { break }
    Start-Sleep -Milliseconds 500
}
Write-Host "Starting $Svc..." -ForegroundColor DarkGray
Start-Service -Name $Svc
$up = $null
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline -and -not $up) {
    Start-Sleep -Seconds 2
    try { $up = (Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/version" -TimeoutSec 5).version } catch { $up = $null }
}
Write-Host ""
if ($up) {
    Write-Host "Rotated. $Svc is up (build $up)." -ForegroundColor Green
} else {
    Write-Host "Rotated, but $Svc did not answer within 45 s (state: $((Get-Service -Name $Svc).Status))." -ForegroundColor Yellow
    Write-Host "Run:  Start-Service $Svc   (elevated) and check logs\nssm-stderr.log."
}
Write-Host "Each browser and device will ask for the token once: paste it when the page asks (Ctrl+V; Win+V shows the clipboard)."
Write-Host "Old links that carried ?token= are dead now; use the pages' own token prompt."
