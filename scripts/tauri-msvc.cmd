@echo off
setlocal

if not "%VS_DEV_CMD%"=="" (
  call "%VS_DEV_CMD%" -arch=x64 -host_arch=x64 >nul
  if errorlevel 1 exit /b %errorlevel%
)

call "%TAURI_CMD%" %*
exit /b %errorlevel%
