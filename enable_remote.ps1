# enable_remote.ps1
# Flip the Anchor R&D control surface to REMOTE (Tailscale) access in one run -
# or revert with -Off. Sets ANCHOR_TOKEN (shared secret) + ANCHOR_BIND (Tailscale
# IP) in the NSSM service env, adds a Tailscale start-dependency, and restarts the
# service (which also loads any new on-disk code).
#
# Run ELEVATED (Administrator). Idempotent. Preserves the existing service env
# (PATH/USERPROFILE/HOME from setup_service_as_john.ps1).
#
#   .\enable_remote.ps1                 # enable; reuse existing token or mint one
#   .\enable_remote.ps1 -Token <tok>    # enable with a specific token
#   .\enable_remote.ps1 -Bind 0.0.0.0   # bind all interfaces instead of tailnet-only
#   .\enable_remote.ps1 -Off            # revert to local-only (loopback, auth off)
#
# SECURITY: the server REFUSES to bind a non-loopback address unless ANCHOR_TOKEN
# is set (enforced in anchor_gui.resolve_bind_host). Mutating endpoints require the
# token; GET endpoints stay open (read-only) to any device that can reach the port.

[CmdletBinding()]
param(
    [string]$Token = "",
    [string]$Bind  = "",
    [switch]$Off
)
$ErrorActionPreference = 'Stop'

# --- self-elevate: works from ANY PowerShell (any folder, elevated or not) ---
# If not already Administrator, relaunch this exact script elevated (UAC prompt),
# forwarding the same args, in a window that STAYS OPEN (-NoExit) so the printed
# token remains visible. $PSCommandPath = this script's full path, so CWD is
# irrelevant. The non-elevated instance then exits.
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Not elevated - relaunching as Administrator (accept the UAC prompt)..." -ForegroundColor Yellow
    $fwd = @('-NoProfile', '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
    if ($Token) { $fwd += @('-Token', $Token) }
    if ($Bind)  { $fwd += @('-Bind',  $Bind) }
    if ($Off)   { $fwd += '-Off' }
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $fwd
    return
}
# Elevated from here on. Run from the script's own folder (defensive).
Set-Location -LiteralPath $PSScriptRoot

$Svc = 'anchor'

# --- locate the nssm that manages the service (install used C:\Tools\nssm) ---
$nssm = if (Test-Path 'C:\Tools\nssm\nssm.exe') { 'C:\Tools\nssm\nssm.exe' }
        else { (Get-Command nssm -ErrorAction Stop).Source }
Write-Host "Using nssm: $nssm" -ForegroundColor DarkGray

# --- read the current AppEnvironmentExtra into an ordered map (preserve it) ---
# Read from the REGISTRY (clean REG_MULTI_SZ String[]), NOT `nssm get` - the
# latter returns UTF-16 that mis-decodes into char-spaced garbage ("P A T H"),
# which would corrupt the merge. nssm is still used to WRITE (it encodes fine).
function Get-ExtraEnv {
    $key = "HKLM:\SYSTEM\CurrentControlSet\Services\$Svc\Parameters"
    $val = (Get-ItemProperty -Path $key -Name AppEnvironmentExtra -ErrorAction SilentlyContinue).AppEnvironmentExtra
    $map = [ordered]@{}
    foreach ($line in @($val)) {
        $line = "$line".Trim()
        if (-not $line) { continue }
        $i = $line.IndexOf('=')
        if ($i -lt 1) { continue }
        $map[$line.Substring(0, $i)] = $line.Substring($i + 1)
    }
    return $map
}
function Set-ExtraEnv($map) {
    $pairs = @()
    foreach ($k in $map.Keys) { $pairs += ("{0}={1}" -f $k, $map[$k]) }
    & $nssm set $Svc AppEnvironmentExtra @pairs | Out-Null
}

$env = Get-ExtraEnv
Write-Host "`n=== current service env keys ===" -ForegroundColor Cyan
($env.Keys -join ', ')

if ($Off) {
    # ---- REVERT to local-only ----
    Write-Host "`nReverting to LOCAL-ONLY (loopback, auth disabled)..." -ForegroundColor Yellow
    $env.Remove('ANCHOR_BIND')   | Out-Null
    $env.Remove('ANCHOR_TOKEN')  | Out-Null
    Set-ExtraEnv $env
    # Drop the Tailscale dependency (set to empty clears it).
    & $nssm set $Svc DependOnService "" | Out-Null
    $bindMsg = "127.0.0.1 (localhost only)"
    $tokenToShow = $null
} else {
    # ---- ENABLE remote ----
    # Bind target: explicit -Bind, else the host's Tailscale IPv4, else known IP.
    if (-not $Bind) {
        try { $Bind = (tailscale ip -4 2>$null | Select-Object -First 1).Trim() } catch {}
        if (-not $Bind) { $Bind = '100.69.215.4' }
    }
    # Token: explicit -Token, else reuse the existing one, else mint a strong one.
    if ($Token) {
        $tok = $Token
    } elseif ($env['ANCHOR_TOKEN']) {
        $tok = $env['ANCHOR_TOKEN']
        Write-Host "Reusing the existing ANCHOR_TOKEN (already configured)." -ForegroundColor DarkGray
    } else {
        $bytes = New-Object byte[] 32
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $tok = ([Convert]::ToBase64String($bytes) -replace '[+/=]', '')
    }

    $env['ANCHOR_TOKEN'] = $tok
    $env['ANCHOR_BIND']  = $Bind
    Set-ExtraEnv $env

    # Start after Tailscale so the interface is assignable (server also bind-retries).
    $ts = Get-Service -Name 'Tailscale' -ErrorAction SilentlyContinue
    if ($ts) { & $nssm set $Svc DependOnService Tailscale | Out-Null }
    else { Write-Host "WARNING: no 'Tailscale' service found - skipping start-dependency." -ForegroundColor Yellow }

    $bindMsg = "${Bind}:8777 (tailnet)"
    $tokenToShow = $tok
}

# --- restart under the new config (also loads any new on-disk code) ---
Write-Host "`nRestarting $Svc ..." -ForegroundColor Cyan
& $nssm restart $Svc | Out-Null
Start-Sleep -Seconds 4

# --- verify ---
Write-Host "`n=== AFTER ===" -ForegroundColor Cyan
$after = Get-CimInstance Win32_Service -Filter "Name='$Svc'"
Write-Host ("State    : {0}" -f $after.State)
Write-Host ("Bind     : {0}" -f $bindMsg)
# Read the env back from the registry (clean) to PROVE it persisted.
$post = Get-ExtraEnv
if (-not $Off) {
    if ($post['ANCHOR_TOKEN']) { Write-Host "ANCHOR_TOKEN: persisted OK" -ForegroundColor Green }
    else { Write-Host "ANCHOR_TOKEN: NOT persisted - the env write failed!" -ForegroundColor Red }
    Write-Host ("ANCHOR_BIND : {0}" -f $post['ANCHOR_BIND'])
}
$listen = Get-NetTCPConnection -State Listen -LocalPort 8777 -ErrorAction SilentlyContinue
if ($listen -and -not $Off -and (@($listen).LocalAddress -contains '127.0.0.1') -and -not (@($listen).LocalAddress -contains $Bind) -and ($Bind -ne '0.0.0.0')) {
    Write-Host "WARNING: still listening on 127.0.0.1 only - remote bind did NOT take effect." -ForegroundColor Red
}
if ($listen) {
    $listen | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize
} else {
    Write-Host "WARNING: nothing listening on 8777 yet - give it a few seconds, then re-check." -ForegroundColor Red
}

if ($tokenToShow) {
    # Resolve the tailnet URL for other devices.
    $tsip = ''
    try { $tsip = (tailscale ip -4 2>$null | Select-Object -First 1).Trim() } catch {}
    if (-not $tsip) { $tsip = '100.69.215.4' }

    Write-Host "`n================  ACCESS TOKEN (store securely)  ================" -ForegroundColor Green
    Write-Host "  $tokenToShow"
    Write-Host "=================================================================" -ForegroundColor Green
    Write-Host "`nOpen the dashboard at:" -ForegroundColor Cyan
    if ($Bind -eq '0.0.0.0') {
        Write-Host "  - This machine:            http://localhost:8777" -ForegroundColor Cyan
        Write-Host ("  - Other devices (Tailscale): http://{0}:8777" -f $tsip) -ForegroundColor Cyan
    } else {
        Write-Host ("  - http://{0}:8777   (use this on THIS machine too;" -f $Bind) -ForegroundColor Cyan
        Write-Host "    localhost will NOT respond - bound to one interface)" -ForegroundColor Cyan
    }
    Write-Host "On first load the page prompts automatically - paste the token" -ForegroundColor Cyan
    Write-Host "above (only the token). It is saved in that browser; you won't be" -ForegroundColor Cyan
    Write-Host "asked again. The SAME token works on every device/browser." -ForegroundColor Cyan
} else {
    Write-Host "`nRemote DISABLED. Dashboard is local-only again at http://localhost:8777" -ForegroundColor Cyan
}
