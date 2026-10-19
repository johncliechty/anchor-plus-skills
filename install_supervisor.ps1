# install_supervisor.ps1  (rearch W16 — External Supervisor Service)
# ---------------------------------------------------------------------------
# Scripted (NOT documented) install of the Anchor supervisor as its OWN NSSM
# service — the second process that owns spawned lane jobs so the dashboard
# (`anchor` service) can restart WITHOUT killing in-flight work (Master Plan
# Phase 5, decision D2).
#
# The supervisor runs `python supervisor.py --serve`, binding a loopback,
# token-authed HTTP IPC port (127.0.0.1 only — never the tailnet). It is
# installed under the SAME account as the `anchor` service (`.\john`) with the
# `anchor` service's environment CLONED so credentials + PATH (claude.exe) and
# ANCHOR_DATA_DIR resolve identically, and with the no-console discipline set
# throughout (AppNoConsole 1 — the supervisor and every child it spawns run
# windowless, per John's standing no-visible-shells rule).
#
# Run once, ELEVATED (nssm install requires admin):
#     powershell -ExecutionPolicy Bypass -File .\install_supervisor.ps1
#
# Options:
#     -ServiceName  <name>   (default: anchor-supervisor)
#     -Port         <int>    (default: 8781)
#     -Token        <secret> (default: reuse the anchor service's ANCHOR_TOKEN,
#                             else a freshly minted 32-byte hex secret)
#     -AnchorService<name>   the service whose account+env we clone (default: anchor)
#
# Remove later (elevated):
#     nssm stop   anchor-supervisor
#     nssm remove anchor-supervisor confirm

param(
    [string]$ServiceName   = "anchor-supervisor",
    [int]   $Port          = 8781,
    [string]$Token         = "",
    [string]$AnchorService = "anchor"
)

$ErrorActionPreference = "Stop"

$AnchorDir = $PSScriptRoot
$Script    = Join-Path $AnchorDir "supervisor.py"

if (-not (Test-Path $Script)) {
    Write-Error "supervisor.py not found at $Script"
    exit 1
}

# --- Locate nssm and python -------------------------------------------------
$nssm = (Get-Command nssm.exe -ErrorAction SilentlyContinue).Source
if (-not $nssm) { $nssm = (Get-Command nssm -ErrorAction SilentlyContinue).Source }
if (-not $nssm) {
    Write-Error "nssm not found on PATH. Install NSSM first."
    exit 1
}

# Use python.exe (NOT pythonw.exe): the server is a long-lived service; NSSM
# owns the process and AppNoConsole 1 keeps it windowless. python.exe gives
# NSSM a clean stdout/stderr to redirect if desired.
$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Write-Error "Could not find python.exe on PATH."
    exit 1
}

Write-Host "Anchor directory : $AnchorDir"
Write-Host "Python exe       : $python"
Write-Host "Supervisor script: $Script"
Write-Host "Service name     : $ServiceName"
Write-Host "IPC port         : $Port (loopback only)"
Write-Host ""

# --- Clone the anchor service's account + environment -----------------------
# ObjectName: run as the SAME account as the anchor service (`.\john`) so the
# supervisor's spawned claude.exe children inherit John's profile/credentials.
$objectName = ".\john"
try {
    $existingObj = (& $nssm get $AnchorService ObjectName) 2>$null
    if ($existingObj -and $existingObj.Trim() -and
        $existingObj.Trim() -ne "LocalSystem") {
        $objectName = $existingObj.Trim()
    }
} catch {
    Write-Host "  (could not read $AnchorService ObjectName; defaulting to $objectName)"
}

# AppEnvironmentExtra: clone the anchor service's extra env so ANCHOR_DATA_DIR,
# ANCHOR_TOKEN, PATH additions etc. match the dashboard exactly.
$clonedEnv = ""
try {
    $clonedEnv = (& $nssm get $AnchorService AppEnvironmentExtra) 2>$null
    if ($clonedEnv) { $clonedEnv = ($clonedEnv -join "`n").Trim() }
} catch {
    Write-Host "  (could not read $AnchorService AppEnvironmentExtra; starting clean)"
}

# --- Resolve the IPC token --------------------------------------------------
if (-not $Token) {
    # Prefer the anchor service's ANCHOR_TOKEN (so the same shared secret gates
    # both surfaces); else mint a fresh one.
    $m = [regex]::Match($clonedEnv, "ANCHOR_SUPERVISOR_TOKEN=([^\r\n]+)")
    if ($m.Success) {
        $Token = $m.Groups[1].Value.Trim()
    } else {
        $bytes = New-Object 'System.Byte[]' 32
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $Token = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
        Write-Host "Minted a fresh ANCHOR_SUPERVISOR_TOKEN."
    }
}

# Build the supervisor's environment block: cloned env + the supervisor's own
# port/token (these override any inherited value).
$envLines = @()
if ($clonedEnv) {
    foreach ($line in ($clonedEnv -split "`r?`n")) {
        if ($line.Trim() -and
            $line -notmatch "^ANCHOR_SUPERVISOR_(PORT|TOKEN|HOST)=") {
            $envLines += $line.Trim()
        }
    }
}
$envLines += "ANCHOR_SUPERVISOR_HOST=127.0.0.1"
$envLines += "ANCHOR_SUPERVISOR_PORT=$Port"
$envLines += "ANCHOR_SUPERVISOR_TOKEN=$Token"
$envBlock = ($envLines -join "`n")

# --- (Re)install the service ------------------------------------------------
$exists = $false
try { $st = (& $nssm status $ServiceName) 2>$null; if ($st) { $exists = $true } } catch {}
if ($exists) {
    Write-Host "Service '$ServiceName' exists — stopping + removing first."
    & $nssm stop   $ServiceName 2>$null | Out-Null
    & $nssm remove $ServiceName confirm 2>$null | Out-Null
    Start-Sleep -Seconds 1
}

Write-Host "Installing '$ServiceName'..."
& $nssm install $ServiceName $python "`"$Script`"" "--serve" | Out-Null

& $nssm set $ServiceName AppDirectory        $AnchorDir            | Out-Null
& $nssm set $ServiceName ObjectName           $objectName          | Out-Null
& $nssm set $ServiceName Start                SERVICE_AUTO_START   | Out-Null
& $nssm set $ServiceName AppNoConsole         1                    | Out-Null   # windowless: no console flash
& $nssm set $ServiceName AppStdout            (Join-Path $AnchorDir "logs\supervisor.out.log") | Out-Null
& $nssm set $ServiceName AppStderr            (Join-Path $AnchorDir "logs\supervisor.err.log") | Out-Null
& $nssm set $ServiceName AppEnvironmentExtra  $envBlock            | Out-Null

Write-Host "Starting '$ServiceName'..."
& $nssm start $ServiceName | Out-Null
Start-Sleep -Seconds 1

Write-Host ""
Write-Host "Supervisor installed as NSSM service '$ServiceName'."
Write-Host "  Account   : $objectName"
Write-Host "  IPC       : http://127.0.0.1:$Port  (token-authed, loopback only)"
Write-Host "  No console: AppNoConsole=1 (windowless; children inherit CREATE_NO_WINDOW)"
Write-Host ""
Write-Host "Point the dashboard at it by setting on the 'anchor' service env:"
Write-Host "    ANCHOR_SUPERVISOR=external"
Write-Host "    ANCHOR_SUPERVISOR_PORT=$Port"
Write-Host "    ANCHOR_SUPERVISOR_TOKEN=<the same secret>"
Write-Host ""
Write-Host "Verify with:  nssm status $ServiceName"
Write-Host "Remove with:  nssm stop $ServiceName; nssm remove $ServiceName confirm"
