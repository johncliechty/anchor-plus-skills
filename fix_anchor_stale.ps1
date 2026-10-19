#requires -Version 5.1
# fix_anchor_stale.ps1 - one-shot, self-verifying repair for the Anchor
# "stale server on port 8777" problem. RUN ELEVATED (Terminal as Admin).
#
# ROOT CAUSE: two NSSM services each run an Anchor server in C:\dev\Anchor:
#   'anchor'        - the legitimate supervisor (C:\Tools\nssm\nssm.exe)
#   'Anchor-Server' - a ROGUE DUPLICATE service (WinGet nssm) from 2026-05-16,
#                     running OLD code. The old code bound with SO_REUSEADDR so
#                     BOTH servers could listen on 8777 at once; requests hit
#                     old or new at random. 'nssm restart anchor' restarts only
#                     one supervisor, so the rogue keeps respawning old code.
#   NSSM/LocalSystem children hide their command line, so we reap by PORT/PID.
#
# This script: removes the rogue service, frees 8777 by PID, restarts 'anchor',
# and verifies the new code is live. Leaves 'anchor', 'ledger', bridge, aurora
# untouched. Idempotent / safe to re-run.

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

function Get-PortOwners {
  return @(Get-NetTCPConnection -LocalPort 8777 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
}

# 1. Remove the rogue Anchor-Server service
Write-Host "`n==> 1/4 Checking for the rogue 'Anchor-Server' service" -ForegroundColor Cyan
$rogue = Get-Service -Name 'Anchor-Server' -ErrorAction SilentlyContinue
if ($rogue) {
  $rp = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\Anchor-Server\Parameters' -ErrorAction SilentlyContinue
  Write-Host ("    Anchor-Server: App={0} Dir={1} Params={2}" -f $rp.Application, $rp.AppDirectory, $rp.AppParameters)
  $isAnchor = ($rp.AppParameters -like '*anchor_gui.py*') -and ($rp.AppDirectory -ieq $AnchorDir)
  if ($isAnchor) {
    & $Nssm stop Anchor-Server 2>&1 | ForEach-Object { "    $_" }
    & $Nssm remove Anchor-Server confirm 2>&1 | ForEach-Object { "    $_" }
    Start-Sleep -Milliseconds 800
    if (Get-Service -Name 'Anchor-Server' -ErrorAction SilentlyContinue) { & sc.exe delete Anchor-Server | Out-Null }
    Write-Host "[ok] Rogue 'Anchor-Server' removed." -ForegroundColor Green
  } else {
    Write-Host "[warn] 'Anchor-Server' params are NOT anchor_gui.py in $AnchorDir; refusing to remove. Inspect manually." -ForegroundColor Yellow
  }
} else {
  Write-Host "[ok] No 'Anchor-Server' service present (already removed)." -ForegroundColor Green
}

# 2. Stop legit service and reap any 8777 squatters by PORT/PID
Write-Host "`n==> 2/4 Stopping 'anchor' and freeing port $Port" -ForegroundColor Cyan
& $Nssm stop anchor 2>&1 | ForEach-Object { "    $_" }
Start-Sleep -Milliseconds 800
foreach ($procId in (Get-PortOwners)) {
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
  if ($p -and ($p.Name -eq 'python.exe' -or $p.Name -eq 'pythonw.exe')) {
    Write-Host "    killing 8777 owner PID $procId ($($p.Name))" -ForegroundColor Magenta
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  } elseif ($p) {
    Write-Host "[warn] Port $Port held by NON-python PID $procId ($($p.Name)); NOT killing. Free it manually." -ForegroundColor Yellow
  }
}
$deadline = (Get-Date).AddSeconds(10)
while ((Get-PortOwners).Count -gt 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 400 }
if ((Get-PortOwners).Count -gt 0) {
  Write-Host ("[FAIL] Port {0} still held by PID(s): {1}" -f $Port, ((Get-PortOwners) -join ', ')) -ForegroundColor Red
  Write-Host "RESULT: STILL STALE" -ForegroundColor Red; exit 1
}
Write-Host "[ok] Port $Port is free." -ForegroundColor Green

# 3. Start the legit service
Write-Host "`n==> 3/4 Starting 'anchor'" -ForegroundColor Cyan
& $Nssm start anchor 2>&1 | ForEach-Object { "    $_" }
$deadline = (Get-Date).AddSeconds(20)
while ((Get-PortOwners).Count -eq 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
if ((Get-PortOwners).Count -eq 0) {
  Write-Host "[FAIL] Service did not bind $Port within 20s." -ForegroundColor Red
  Write-Host "RESULT: STILL STALE" -ForegroundColor Red; exit 1
}
Write-Host ("[ok] anchor is listening on {0} (PID {1})." -f $Port, ((Get-PortOwners) -join ',')) -ForegroundColor Green

# 4. Verify the new code is serving
Write-Host "`n==> 4/4 Verifying new code is live" -ForegroundColor Cyan
# rearch-2026-07 W2 consumer token path: /api/rnd/tail is in the to-be-gated
# data-plane batch. When ANCHOR_TOKEN is set in this shell's environment,
# present it via the standard Authorization header so this probe keeps working
# after the auth flip (W8/W9). Absent env -> no header (local back-compat).
$AuthHeaders = @{}
if ($env:ANCHOR_TOKEN) { $AuthHeaders['Authorization'] = "Bearer $($env:ANCHOR_TOKEN)" }
function Get-TailCode {
  try {
    $r = Invoke-WebRequest "$Base/api/rnd/tail" -Headers $AuthHeaders -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    return [int]$r.StatusCode
  } catch [System.Net.WebException] {
    if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
    return -1
  } catch { return -1 }
}
$code = -1
for ($i = 0; $i -lt 12; $i++) {
  $code = Get-TailCode
  if ($code -eq 400 -or $code -eq 404) { break }
  Start-Sleep -Milliseconds 600
}
$tailOk = ($code -eq 400)
if ($code -eq 400) { Write-Host "[ok] /api/rnd/tail returned 400 (new route present)." -ForegroundColor Green }
elseif ($code -eq 404) { Write-Host "[FAIL] /api/rnd/tail returned 404 (OLD code still serving)." -ForegroundColor Red }
else { Write-Host "[FAIL] /api/rnd/tail unreachable (code $code)." -ForegroundColor Red }

$uiOk = $false
try {
  $h = (Invoke-WebRequest "$Base/" -Headers $AuthHeaders -UseBasicParsing -TimeoutSec 6 -ErrorAction Stop).Content
  $marker1 = "showView('rnd')"
  $uiOk = $h.Contains($marker1) -and $h.Contains('New Project')
  if ($uiOk) { Write-Host "[ok] Dashboard has the RnD tab and New Project button." -ForegroundColor Green }
  else { Write-Host "[FAIL] Dashboard HTML missing the RnD markers." -ForegroundColor Red }
} catch {
  Write-Host "[FAIL] GET / failed: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
if ($tailOk -and $uiOk) {
  Write-Host "RESULT: NEW UI LIVE  (now hard-refresh the browser: Ctrl+Shift+R)" -ForegroundColor Green
  exit 0
} else {
  Write-Host "RESULT: STILL STALE" -ForegroundColor Red
  exit 1
}
