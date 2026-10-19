@echo off
"%GITGUARD_PYTHON%" "%~dp0gitguard.py" %*
exit /b %ERRORLEVEL%
