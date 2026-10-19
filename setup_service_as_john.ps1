# setup_service_as_john.ps1
# SETUP gate §1 (planning/rnd-v1/SETUP.md): run the Anchor NSSM service as `john`
# so headless `claude -p` R&D jobs can reach ~\.claude\.credentials.json.
#
# Run ELEVATED (Administrator). Prompts securely for john's Windows password;
# the password is never written to disk, the transcript, or shell history.
# Idempotent: safe to re-run.

#requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$Svc      = 'anchor'
$Account  = '.\john'                       # local account john on PUTER
$ClaudeBin = 'C:\Users\john\.local\bin'             # where claude.exe lives
$GeminiBin = 'C:\Users\john\AppData\Roaming\npm'    # where gemini.cmd/.ps1 lives (npm global)
$Profile  = 'C:\Users\john'                 # john's profile root (for USERPROFILE/HOME) — also where ~\.claude and ~\.gemini creds live

# --- locate the nssm binary that manages the service (install used C:\Tools\nssm) ---
$nssm = if (Test-Path 'C:\Tools\nssm\nssm.exe') { 'C:\Tools\nssm\nssm.exe' }
        else { (Get-Command nssm -ErrorAction Stop).Source }
Write-Host "Using nssm: $nssm" -ForegroundColor DarkGray

# --- show current state ---
Write-Host "`n=== BEFORE ===" -ForegroundColor Cyan
$before = Get-CimInstance Win32_Service -Filter "Name='$Svc'"
Write-Host ("StartName : {0}" -f $before.StartName)
Write-Host ("State     : {0}" -f $before.State)

# --- secure password prompt ---
Write-Host "`nEnter the Windows password for $Account (input hidden):" -ForegroundColor Yellow
$sec  = Read-Host -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
try   { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

if ([string]::IsNullOrEmpty($plain)) { throw "No password entered; aborting." }

# --- 1. service identity (nssm also grants SeServiceLogonRight to the account) ---
Write-Host "`nSetting service logon account -> $Account ..." -ForegroundColor Cyan
& $nssm set $Svc ObjectName $Account $plain | Out-Null
$plain = $null   # drop plaintext ASAP

# --- 2. environment: PATH for claude.exe AND gemini + pin USERPROFILE/HOME (service won't load profile) ---
#     USERPROFILE/HOME also makes ~\.claude\.credentials.json and ~\.gemini\oauth_creds.json resolve.
Write-Host "Setting AppEnvironmentExtra (PATH [claude+gemini] + USERPROFILE + HOME) ..." -ForegroundColor Cyan
& $nssm set $Svc AppEnvironmentExtra `
    "PATH=%PATH%;$ClaudeBin;$GeminiBin" `
    "USERPROFILE=$Profile" `
    "HOME=$Profile" | Out-Null

# --- restart under the new identity ---
Write-Host "Restarting $Svc ..." -ForegroundColor Cyan
& $nssm restart $Svc | Out-Null
Start-Sleep -Seconds 3

# --- verify ---
Write-Host "`n=== AFTER ===" -ForegroundColor Cyan
$after = Get-CimInstance Win32_Service -Filter "Name='$Svc'"
Write-Host ("StartName : {0}" -f $after.StartName)
Write-Host ("State     : {0}" -f $after.State)

Write-Host "`nConfigured AppEnvironmentExtra:" -ForegroundColor DarkGray
& $nssm get $Svc AppEnvironmentExtra

$listener = Get-NetTCPConnection -State Listen -LocalPort 8777 -ErrorAction SilentlyContinue
if ($listener) {
    $count = @($listener).Count
    $owner = (Get-Process -Id $listener[0].OwningProcess -IncludeUserName -ErrorAction SilentlyContinue).UserName
    Write-Host ("`n8777 listeners: {0}  PID {1}  owner {2}" -f $count, $listener[0].OwningProcess, $owner) -ForegroundColor Green
    if ($count -ne 1) { Write-Host "WARNING: expected exactly 1 listener on 8777." -ForegroundColor Red }
} else {
    Write-Host "`nWARNING: nothing listening on 8777 after restart." -ForegroundColor Red
}

try {
    $resp = Invoke-WebRequest 'http://localhost:8777/api/status' -UseBasicParsing -TimeoutSec 5
    Write-Host ("Dashboard /api/status -> HTTP {0}" -f $resp.StatusCode) -ForegroundColor Green
} catch {
    Write-Host ("Dashboard probe failed: {0}" -f $_.Exception.Message) -ForegroundColor Red
}

Write-Host "`nDone. Next: from the normal (non-elevated) john session, run the live" -ForegroundColor Cyan
Write-Host "credential smoke test (launch a tiny R&D research lane and tail it to done)." -ForegroundColor Cyan
