@echo off
REM Animated release build — thin shim over release-ui.ps1, which runs
REM scripts\release.bat unchanged and renders the live checklist +
REM progress bar. Double-click friendly; pauses on exit like release.bat.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0release-ui.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
