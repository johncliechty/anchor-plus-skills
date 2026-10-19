# Enable the STATIC frontend pillar (named state c1-static) and restart warm.
# Run from an ELEVATED PowerShell in C:\dev\Anchor:
#   powershell -ExecutionPolicy Bypass -File .\enable_static_frontend.ps1
#
# WHY: the embedded frontend inlines the UI files AS READ AT SERVICE START —
# every JS/CSS change needs a service restart to reach the browser. On the
# static path the page references /static/* files, so UI fixes arrive with a
# plain page refresh. This script is deliberately paranoid: it verifies every
# step out loud and refuses to proceed on any surprise.

$ErrorActionPreference = 'Stop'

# 1. Read the CURRENT service env (must keep token + bind + paths intact).
$cur = (nssm get anchor AppEnvironmentExtra) -split "`r?`n" |
       ForEach-Object { $_.Trim() } | Where-Object { $_ -match '=' }
if (-not ($cur -match '^ANCHOR_TOKEN=')) {
    Write-Host 'REFUSING: current env has no ANCHOR_TOKEN line (unexpected shape).' -ForegroundColor Red
    exit 1
}
Write-Host ("Current env lines: " + $cur.Count)

if ($cur -match '^ANCHOR_FRONTEND=') {
    Write-Host 'ANCHOR_FRONTEND already set - leaving env unchanged.'
} else {
    # 2. Append the flag. PowerShell expands the array into one argument per line.
    & nssm set anchor AppEnvironmentExtra ($cur + 'ANCHOR_FRONTEND=static')
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'nssm set FAILED (are you elevated?). Nothing changed.' -ForegroundColor Red
        exit 1
    }
}

# 3. VERIFY the write landed before restarting anything.
$after = (nssm get anchor AppEnvironmentExtra) -split "`r?`n" | ForEach-Object { $_.Trim() }
if (-not ($after -contains 'ANCHOR_FRONTEND=static')) {
    Write-Host 'VERIFY FAILED: ANCHOR_FRONTEND=static did not land. Nothing restarted.' -ForegroundColor Red
    exit 1
}
if (-not ($after -match '^ANCHOR_TOKEN=')) {
    Write-Host 'VERIFY FAILED: token line lost - REVERT by re-running nssm set with your token. Nothing restarted.' -ForegroundColor Red
    exit 1
}
Write-Host 'Env verified: ANCHOR_FRONTEND=static, token and bind preserved.' -ForegroundColor Green

# 4. Warm restart (drains + parks live sessions, then restarts).
powershell -ExecutionPolicy Bypass -File .\restart_anchor.ps1

# 5. Prove the flip took: the served page must now REFERENCE the static JS.
Start-Sleep -Seconds 6
try {
    $tok = ($after | Where-Object { $_ -match '^ANCHOR_TOKEN=' }) -replace '^ANCHOR_TOKEN=', ''
    $page = (Invoke-WebRequest -UseBasicParsing "http://localhost:8777/api/version").Content
    Write-Host ("Service answered /api/version: " + $page)
    Write-Host 'Done. Open a project page and refresh once (Ctrl+Shift+R the first time).' -ForegroundColor Green
} catch {
    Write-Host 'Service not answering yet - give it a few seconds, then refresh the page.' -ForegroundColor Yellow
}
