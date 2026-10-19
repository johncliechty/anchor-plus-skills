<#
.SYNOPSIS
  W11 (C6) — scripted, rollback-able Anchor data-dir migration (ops wrapper).

.DESCRIPTION
  Moves Anchor's runtime state OUT of the repo as ONE unit, wrapping the Python
  migration core (tools/migrate_data_dir.py) with the service lifecycle:

    stop service -> migrate_data + path-rewrite (python core) -> point NSSM at
    the new ANCHOR_DATA_DIR -> start service -> healthcheck probe -> (on success)
    leave the OLD dir read-only for a week; (on failure) roll back to the old dir.

  The Python core never mutates the old root, so the old root is always an intact
  rollback source. Run ELEVATED (nssm + service control need admin).

.PARAMETER NewRoot
  The out-of-repo destination, e.g. C:\AnchorData. Must be empty / not exist.

.PARAMETER OldRoot
  The current in-repo data root (defaults to this repo's folder).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\migrate_data_dir.ps1 -NewRoot C:\AnchorData
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$NewRoot,
    [string]$OldRoot = $PSScriptRoot,
    [string]$ServiceName = "anchor",
    [switch]$SkipHealthcheck
)

$ErrorActionPreference = "Stop"
$py = "python"

function Fail($msg) { Write-Error $msg; exit 1 }

Write-Host "== Anchor data-dir migration (W11/C6) =="
Write-Host "   old: $OldRoot"
Write-Host "   new: $NewRoot"

# 1) Stop the service so nothing writes mid-copy.
Write-Host "-- stopping service '$ServiceName' ..."
try { nssm stop $ServiceName | Out-Null } catch { Write-Warning "nssm stop: $_" }

# 2) Run the Python migration core (copy + path-rewrite + verify + arm reaper).
Write-Host "-- migrating (copy + path-rewrite + verify) ..."
$out = & $py (Join-Path $OldRoot "tools\migrate_data_dir.py") $OldRoot $NewRoot
$code = $LASTEXITCODE
Write-Host $out
if ($code -ne 0) {
    Write-Warning "migration core FAILED (rolled back the new root). Restarting from the OLD dir."
    nssm start $ServiceName | Out-Null
    Fail "migration aborted; service restarted on the old data dir (no changes)."
}

# 3) Point the service at the new ANCHOR_DATA_DIR.
Write-Host "-- pointing NSSM AppEnvironmentExtra ANCHOR_DATA_DIR -> $NewRoot"
nssm set $ServiceName AppEnvironmentExtra "ANCHOR_DATA_DIR=$NewRoot" | Out-Null

# 4) Start the service (first post-move boot runs the reaper in DRY-RUN).
Write-Host "-- starting service ..."
nssm start $ServiceName | Out-Null
Start-Sleep -Seconds 3

# 5) Healthcheck probe against the live service.
if (-not $SkipHealthcheck) {
    Write-Host "-- healthcheck probe ..."
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8777/" -UseBasicParsing -TimeoutSec 10
        if ($r.StatusCode -ne 200) { throw "status $($r.StatusCode)" }
        Write-Host "   healthcheck OK ($($r.StatusCode))"
    } catch {
        Write-Warning "healthcheck FAILED: $_. Rolling back to the old data dir."
        nssm stop $ServiceName | Out-Null
        nssm set $ServiceName AppEnvironmentExtra "" | Out-Null
        nssm start $ServiceName | Out-Null
        Fail "rolled back: service restarted on the old data dir. New root left at $NewRoot for inspection."
    }
}

# 6) Preserve the OLD data dir read-only for a week (belt-and-suspenders rollback).
Write-Host "-- marking the OLD data stores read-only (one-week preservation) ..."
foreach ($n in @("rnd_registry.json", "dashboard.html")) {
    $p = Join-Path $OldRoot $n
    if (Test-Path $p) { Set-ItemProperty -Path $p -Name IsReadOnly -Value $true }
}

Write-Host "== migration complete. ANCHOR_DATA_DIR = $NewRoot =="
Write-Host "   Keep the old dir untouched for ~1 week, then archive it."
exit 0
