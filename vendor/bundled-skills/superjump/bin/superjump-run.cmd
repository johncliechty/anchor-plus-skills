@echo off
REM Space-free launch shim. Always resolve this script, then the .mjs beside it.
setlocal
set "HERE=%~dp0"
node "%HERE%superjump-run.mjs" %*
endlocal
