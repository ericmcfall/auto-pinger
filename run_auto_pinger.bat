@echo off
REM Double-click this file to start Auto Ping'er with config.json from this folder.
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 auto_pinger.py %*
) else (
    python auto_pinger.py %*
)
pause
