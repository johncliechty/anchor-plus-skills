@echo off
rem Gate 5 Stage 1 (LITE) — schtasks breakaway wrapper (journal 0090: the wrapper owns the log file;
rem the launcher writes stderr only). Drafter = coding_family (chatgpt), Sharks/Judge = review_family (claude).
set CRUCIBLE_AGENT_LIVE=1
set OUT=<path>
cd /d <path>
echo [%date% %time%] gate5 stage1 wrapper start >> "%OUT%\_stage1-run.log"
node _gate5_stage1.mjs >> "%OUT%\_stage1-run.log" 2>&1
echo [%date% %time%] gate5 stage1 wrapper exit %errorlevel% >> "%OUT%\_stage1-run.log"
