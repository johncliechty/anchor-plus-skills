#requires -Version 5.1
# restart_anchor.ps1 - the CANONICAL warm restart for the Anchor service.
# RUN ELEVATED (Terminal as Admin) - nssm start/stop require it.
#
# WHY THIS EXISTS (rearch W3, Phase-2 durable saving):
#   A bare `nssm restart anchor` kills the server process and every live PTY it
#   owns - so any open terminal session loses its context ("cold" on reopen).
#   This wrapper first runs the pre-designed GRACEFUL DRAIN
#   (tools/pre_restart_drain.py) WHILE THE SERVICE IS STILL UP, which for every
#   live session: parks it (close_session -> STATUS_IDLE, worktree kept),
#   PERSISTS its produced docs into the main project, and CACHES its warm-resume
#   summary - all to disk, so it survives the stop. THEN it restarts the service.
#   Result: a deploy/restart is warm-by-design - clicking a parked tile after the
#   restart resumes WARM (continue_session finds the persisted docs + cached
#   summary), never dead context.
#
#   W5 (2026-10-09): the drain FAILS CLOSED. It reads the service token from the service itself, asks the service to
#   park every cockpit engine, and if anything did not park (401, a bad answer, an engine or session that failed) the
#   restart STOPS before the service is touched. A deliberate cold restart: -Cold (or nssm restart anchor).
#
# Idempotent / safe to re-run. Leaves 'ledger', bridge, aurora untouched.

param([switch]$Cold)
$ErrorActionPreference = 'Continue'
$Port = 8777
$Base = "http://127.0.0.1:$Port"
$AnchorDir = 'C:\dev\Anchor'

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "[FAIL] Not elevated. Re-run from Terminal (Admin)." -ForegroundColor Red; exit 2 }

$Nssm = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if (-not $Nssm) {
  foreach ($c in @("C:\Tools\nssm\nssm.exe", "$env:LOCALAPPDATA\Microsoft\WinGet\Links\nssm.exe", "C:\Windows\System32\nssm.exe")) {
    if (Test-Path $c) { $Nssm = $c; break }
  }
}
if (-not $Nssm) { Write-Host "[FAIL] nssm.exe not found." -ForegroundColor Red; exit 2 }
Write-Host "[ok] Using nssm: $Nssm" -ForegroundColor Green

$Py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Py) { $Py = (Get-Command python3 -ErrorAction SilentlyContinue).Source }

function Get-PortOwners {
  return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
}

# 1. WARM DRAIN (while the service is still up) - park every live session warm.
Write-Host "`n==> 1/3 Warm drain (park live sessions, persist docs + cache summaries)" -ForegroundColor Cyan
if ($Cold) {
  Write-Host "[note] -Cold: the drain is skipped by request; live steward turns end with the process." -ForegroundColor Yellow
} else {
  # the service's own token (the admin shell has none): nssm keeps it in AppEnvironmentExtra
  if (-not $env:ANCHOR_TOKEN) {
    $extra = ((& $Nssm get anchor AppEnvironmentExtra 2>$null) -join "`n") -replace "`0", ''
    $m = [regex]::Match($extra, '(?m)^ANCHOR_TOKEN=(.+)$')
    if ($m.Success) { $env:ANCHOR_TOKEN = $m.Groups[1].Value.Trim() }
  }
  if (-not $env:ANCHOR_TOKEN) {
    Write-Host "[STOP] The service token could not be read, so the stewards cannot be parked. Nothing was changed; the service was not stopped. (A cold restart: -Cold)" -ForegroundColor Red
    Write-Host "RESULT: RESTART STOPPED BEFORE ANY CHANGE" -ForegroundColor Red; exit 3
  }
  Push-Location $AnchorDir
  try {
    & $Py "tools\pre_restart_drain.py" 2>&1 | ForEach-Object { "    $_" }
    $drainExit = $LASTEXITCODE
  } catch { $drainExit = 99 } finally { Pop-Location }
  if ($drainExit -ne 0) {
    Write-Host "[STOP] The drain did not park everything (exit $drainExit, above). Nothing was changed; the service was not stopped. Look, or choose a cold restart: -Cold" -ForegroundColor Red
    Write-Host "RESULT: RESTART STOPPED BEFORE ANY CHANGE" -ForegroundColor Red; exit 3
  }
  Write-Host "[ok] Warm drain complete: every steward engine and session parked." -ForegroundColor Green
}

# 2. Restart the service.
Write-Host "`n==> 2/3 Restarting 'anchor'" -ForegroundColor Cyan
$OldPids = @(Get-PortOwners)
& $Nssm stop anchor 2>&1 | ForEach-Object { "    $_" }
# The start waits for a CONFIRMED stopped service - the service reports Stopped AND nothing listens on the port.
$deadline = (Get-Date).AddSeconds(60)
do {
  $svc = (Get-Service anchor -ErrorAction SilentlyContinue).Status
  $stopped = ($svc -eq 'Stopped') -and ((Get-PortOwners).Count -eq 0)
  if (-not $stopped) { Start-Sleep -Milliseconds 500 }
} while (-not $stopped -and (Get-Date) -lt $deadline)
if (-not $stopped) {
  Write-Host "[FAIL] The service did not stop (status: $svc; listeners: $((Get-PortOwners) -join ',')). It keeps running the build it had." -ForegroundColor Red
  Write-Host "RESULT: RESTART FAILED - NOTHING CHANGED" -ForegroundColor Red; exit 1
}
& $Nssm start anchor 2>&1 | ForEach-Object { "    $_" }
# The port shows LISTENING only once the server's boot reconcile is done (it
# binds at once but listen()s when ready) — under load that has taken 80s+.
$deadline = (Get-Date).AddSeconds(180)
while ((Get-PortOwners).Count -eq 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
if ((Get-PortOwners).Count -eq 0) {
  Write-Host "[FAIL] Service did not become ready (listening) on $Port within 180s." -ForegroundColor Red
  Write-Host "RESULT: RESTART FAILED" -ForegroundColor Red; exit 1
}
$NewPids = @(Get-PortOwners)
if (@($NewPids | Where-Object { $OldPids -contains $_ }).Count -gt 0) {
  Write-Host "[FAIL] The listener on $Port is the process from before the restart (PID $($NewPids -join ',')) - the restart did not take." -ForegroundColor Red
  Write-Host "RESULT: RESTART FAILED" -ForegroundColor Red; exit 1
}
Write-Host ("[ok] anchor is listening on {0} (PID {1}, a new process)." -f $Port, ($NewPids -join ',')) -ForegroundColor Green

# 3. Verify the service is serving.
Write-Host "`n==> 3/3 Verifying the dashboard is live" -ForegroundColor Cyan
$AuthHeaders = @{}
if ($env:ANCHOR_TOKEN) { $AuthHeaders['Authorization'] = "Bearer $($env:ANCHOR_TOKEN)" }
$uiOk = $false
for ($i = 0; $i -lt 12; $i++) {
  try {
    $h = (Invoke-WebRequest "$Base/" -Headers $AuthHeaders -UseBasicParsing -TimeoutSec 6 -ErrorAction Stop).Content
    if ($h.Contains("showView('rnd')") -and $h.Contains('New Project')) { $uiOk = $true; break }
  } catch { }
  Start-Sleep -Milliseconds 600
}
Write-Host ""
if ($uiOk) {
  Write-Host "RESULT: ANCHOR RESTARTED WARM  (parked tiles resume warm; hard-refresh browser Ctrl+Shift+R)" -ForegroundColor Green
  exit 0
} else {
  Write-Host "[FAIL] Dashboard did not return the expected markers." -ForegroundColor Red
  Write-Host "RESULT: RESTART FAILED" -ForegroundColor Red; exit 1
}
