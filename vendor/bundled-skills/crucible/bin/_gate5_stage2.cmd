@echo off
rem Gate 5 Stage 2 (LITE) — schtasks breakaway wrapper (the wrapper owns the log; launcher writes stderr only).
set CRUCIBLE_AGENT_LIVE=1
set OUT=<path>
cd /d <path>
echo [%date% %time%] gate5 stage2 wrapper start >> "%OUT%\_stage2-run.log"
node _gate5_stage2.mjs >> "%OUT%\_stage2-run.log" 2>&1
echo [%date% %time%] gate5 stage2 wrapper exit %errorlevel% >> "%OUT%\_stage2-run.log"
