@echo off
setlocal EnableExtensions
title Uninstall Anchor - Ghost World Labs
set "ANCHOR_WS=C:\dev"
set "ANCHOR_SKILLS_DIR=%ANCHOR_WS%\skills"
set "ANCHOR_APP_DIR=%ANCHOR_WS%\Anchor"

echo ============================================================================
echo   Anchor - Clean Uninstaller [Ghost World Labs]
echo ============================================================================
echo.

if /I "%COMPUTERNAME%"=="PUTER" (
    echo Refusing to run collaborator uninstaller on primary author host.
    if "%~1"=="--silent" exit /b 1
    pause
    exit /b 1
)
if /I "%COMPUTERNAME%"=="GWL-SERVER" (
    echo Refusing to run collaborator uninstaller on primary author host.
    if "%~1"=="--silent" exit /b 1
    pause
    exit /b 1
)

echo [1/5] Stopping local Anchor windows and verified Anchor background services...
taskkill /IM "Anchor.exe" /T /F >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$pids = Get-NetTCPConnection -LocalPort 8777,48484 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($procId in $pids) { if ($procId -gt 4) { $proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $procId) -ErrorAction SilentlyContinue; if ($proc -and ($proc.Name -match '^Anchor' -or $proc.CommandLine -match 'anchor_gui\.py|zombie_hunter|launch_anchor')) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } } }" >nul 2>&1

echo [2/5] Removing desktop and Start Menu shortcuts...
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Anchor.lnk" (
    del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Anchor.lnk" >nul 2>&1
)
if exist "%USERPROFILE%\Desktop\Anchor.lnk" (
    del /f /q "%USERPROFILE%\Desktop\Anchor.lnk" >nul 2>&1
)

echo [3/5] Removing Anchor desktop shell profile and backing up local .anchor state...
if exist "%LOCALAPPDATA%\anchor-shell" (
    rmdir /s /q "%LOCALAPPDATA%\anchor-shell" >nul 2>&1
)
if exist "%USERPROFILE%\.anchor" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$src = Join-Path $env:USERPROFILE '.anchor'; $bak = Join-Path $env:USERPROFILE ('Anchor-uninstall-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss')); if (Test-Path -LiteralPath $src) { Move-Item -LiteralPath $src -Destination $bak -Force -ErrorAction SilentlyContinue }" >nul 2>&1
)

echo [4/5] Removing Anchor-installed bundled skills while preserving custom skills...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$roots = @($env:ANCHOR_SKILLS_DIR, (Join-Path $env:USERPROFILE '.claude\skills'), (Join-Path $env:USERPROFILE '.agents\skills'), (Join-Path $env:USERPROFILE '.gemini\antigravity\skills')); foreach ($r in $roots) { if ($r -and (Test-Path -LiteralPath $r)) { Get-ChildItem -LiteralPath $r -Force -ErrorAction SilentlyContinue | Where-Object { $_.PSIsContainer } | ForEach-Object { $p = $_.FullName; $marker = Join-Path $p '.anchor-onboard-installed'; $isLink = [bool]($_.Attributes -band [IO.FileAttributes]::ReparsePoint); if ($isLink -and (Test-Path -LiteralPath $marker)) { cmd.exe /c rmdir $p >$null 2>&1 } elseif (-not $isLink -and (Test-Path -LiteralPath $marker)) { Get-ChildItem -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | ForEach-Object { cmd.exe /c rmdir $_.FullName >$null 2>&1 }; Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue } } } }" >nul 2>&1

echo [5/5] Removing collaborator Anchor application folder while preserving all user projects...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$regKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\GhostWorldLabsAnchor'; $regLoc = ''; if (Test-Path $regKey) { $regLoc = [string]((Get-ItemProperty -Path $regKey -ErrorAction SilentlyContinue).InstallLocation) }; $cands = @($regLoc, $env:ANCHOR_APP_DIR, (Join-Path $env:ANCHOR_WS 'anchor-plus-skills')) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique; foreach ($dir in $cands) { $gui = Join-Path $dir 'anchor_gui.py'; if (-not (Test-Path -LiteralPath $gui)) { continue }; $edFile = Join-Path $dir 'anchor-edition.json'; $gitCfg = Join-Path $dir '.git\config'; $isCollab = $false; $isAdmin = $false; if (Test-Path -LiteralPath $edFile) { try { $ed = Get-Content -LiteralPath $edFile -Raw | ConvertFrom-Json; if ($ed.edition -eq 'admin') { $isAdmin = $true } elseif ($ed.edition -in @('collaborator','share','shared','client')) { $isCollab = $true } } catch {} }; if ((-not $isAdmin) -and (-not $isCollab) -and (Test-Path -LiteralPath $gitCfg)) { $gtxt = Get-Content -LiteralPath $gitCfg -Raw -ErrorAction SilentlyContinue; if ($gtxt -match 'ghostworldlabs-anchor|anchor-plus-skills') { $isCollab = $true } }; if ($isAdmin) { Write-Host ('Preserving admin installation at ' + $dir) } elseif ($isCollab) { Write-Host ('Scheduling removal of collaborator installation at ' + $dir); Start-Process -WindowStyle Hidden -FilePath 'cmd.exe' -ArgumentList ('/c ping 127.0.0.1 -n 3 >nul & rmdir /s /q \"' + $dir + '\" >nul 2>&1') } else { Write-Host ('Preserving developer repository at ' + $dir) } }"

reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\GhostWorldLabsAnchor" /f >nul 2>&1

echo.
echo Anchor has been cleanly uninstalled. Your personal project folders were NOT deleted.
if "%~1"=="--silent" exit /b 0
pause
