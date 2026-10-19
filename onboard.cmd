@echo off
REM Cold-start: double-click or run from package root after git clone.
REM Delegates to onboard.ps1 (Python ensure + python -m share_onboard).
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0onboard.ps1" %*
exit /b %ERRORLEVEL%
