@echo off
if "%~1"=="__INNER__" goto :main

cmd /k "%~f0" __INNER__ %*
exit /b

:main
setlocal EnableExtensions EnableDelayedExpansion
title Reliability Tools Desktop - Release Build
set "NO_PAUSE=0"
if /I "%~2"=="--no-pause" set "NO_PAUSE=1"

set "SCRIPT_DIR=%~dp0"
set "ROOT_DIR=%SCRIPT_DIR%.."
set "REPO_ROOT=%ROOT_DIR%"
set "OUTPUT_DIR=%ROOT_DIR%\local_build"
set "LOGS_DIR=%ROOT_DIR%\logs"
set "OUTPUT_EXE=%OUTPUT_DIR%\ReliabilityToolsDesktop.exe"
set "PACKAGED_EXE_NAME=reliability-tools-desktop.exe"
set "PACKAGED_EXE="
set "BACKEND_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"

for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format \"yyyyMMdd_HHmmss\""') do set "TIMESTAMP=%%i"
if not defined TIMESTAMP set "TIMESTAMP=unknown_%RANDOM%"
set "LOGFILE=%LOGS_DIR%\release_%TIMESTAMP%.log"

echo ============================================================ > "%LOGFILE%"
echo  RELIABILITY TOOLS DESKTOP - RELEASE BUILD >> "%LOGFILE%"
echo  Started %DATE% %TIME% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

echo.
echo ============================================================
echo   RELIABILITY TOOLS DESKTOP - RELEASE BUILD
echo ============================================================
echo.
echo   Output log: %LOGFILE%
echo.

pushd "%ROOT_DIR%"
if errorlevel 1 goto :fail

echo [1/11] Checking toolchain...
where node >nul 2>&1 || goto :missing_node
where npm >nul 2>&1 || goto :missing_npm
echo [INFO] node and npm detected >> "%LOGFILE%"

if not exist "%BACKEND_PYTHON%" goto :missing_backend_python

echo [2/11] Typechecking frontend...
call npm run typecheck >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :typecheck_failed

echo [3/11] Typechecking Rust bridge (cargo check)...
pushd "%REPO_ROOT%\src-tauri"
cargo check --quiet >> "%LOGFILE%" 2>&1
set "CARGO_CHECK_RC=%ERRORLEVEL%"
popd
if not "%CARGO_CHECK_RC%"=="0" goto :cargo_check_failed

echo [4/11] Running backend security audit...
pushd "%REPO_ROOT%\backend\python"
"%BACKEND_PYTHON%" -m common.security_audit --strict >> "%LOGFILE%" 2>&1
set "AUDIT_RC=%ERRORLEVEL%"
popd
if not "%AUDIT_RC%"=="0" goto :security_audit_failed

echo [5/11] Running backend tests...
"%BACKEND_PYTHON%" -m pytest backend\tests -q >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :backend_tests_failed

echo [6/11] Running frontend tests...
call npm test >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :tests_failed

echo [7/11] Building Python sidecar exe...
"%BACKEND_PYTHON%" scripts\build_sidecar.py >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :sidecar_build_failed

echo [8/11] Building portable desktop exe...
call npm run tauri:build:portable >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :build_failed

echo [9/11] Locating packaged executable...
if exist "%ROOT_DIR%\src-tauri\target\x86_64-pc-windows-msvc\release\%PACKAGED_EXE_NAME%" (
    set "PACKAGED_EXE=%ROOT_DIR%\src-tauri\target\x86_64-pc-windows-msvc\release\%PACKAGED_EXE_NAME%"
)
if not defined PACKAGED_EXE if exist "%ROOT_DIR%\src-tauri\target\release\%PACKAGED_EXE_NAME%" (
    set "PACKAGED_EXE=%ROOT_DIR%\src-tauri\target\release\%PACKAGED_EXE_NAME%"
)
if not defined PACKAGED_EXE (
    for /f "delims=" %%i in ('dir /b /s "%ROOT_DIR%\src-tauri\target\%PACKAGED_EXE_NAME%" 2^>nul') do (
        if not defined PACKAGED_EXE set "PACKAGED_EXE=%%i"
    )
)
if not defined PACKAGED_EXE goto :missing_packaged_exe

copy /y "%PACKAGED_EXE%" "%OUTPUT_EXE%" >nul
if errorlevel 1 goto :copy_failed
echo [INFO] Copied packaged exe to %OUTPUT_EXE% >> "%LOGFILE%"

echo [10/11] Running packaged self-test...
"%OUTPUT_EXE%" --self-test >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :selftest_failed

echo [11/11] Running packaged backend self-test...
"%OUTPUT_EXE%" --self-test-backend >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :backend_selftest_failed

echo.
echo ============================================================
echo   STATUS: SUCCESS
echo ============================================================
echo.
echo   Portable EXE:
echo   %OUTPUT_EXE%
echo.
echo   Log:
echo   %LOGFILE%
echo.
popd
call :pause_if_needed
exit /b 0

:missing_node
echo [ERROR] node is not available on PATH. >> "%LOGFILE%"
echo.
echo [FAILED] node is not available on PATH.
goto :fail

:missing_npm
echo [ERROR] npm is not available on PATH. >> "%LOGFILE%"
echo.
echo [FAILED] npm is not available on PATH.
goto :fail

:missing_backend_python
echo [ERROR] Could not find backend Python at %BACKEND_PYTHON%. >> "%LOGFILE%"
echo.
echo [FAILED] Backend Python interpreter was not found.
goto :fail

:typecheck_failed
echo [ERROR] Frontend typecheck (tsc) reported errors. >> "%LOGFILE%"
echo.
echo [FAILED] Frontend typecheck failed. See log for details.
goto :fail

:cargo_check_failed
echo [ERROR] Rust bridge `cargo check` reported errors. >> "%LOGFILE%"
echo.
echo [FAILED] Rust bridge did not typecheck. See log for details.
goto :fail

:security_audit_failed
echo [ERROR] Backend security audit found violations. >> "%LOGFILE%"
echo.
echo [FAILED] Security audit failed. See log for details.
goto :fail

:backend_tests_failed
echo [ERROR] Backend pytest run failed. >> "%LOGFILE%"
echo.
echo [FAILED] Backend tests failed. See log for details.
goto :fail

:tests_failed
echo [ERROR] npm test failed. >> "%LOGFILE%"
echo.
echo [FAILED] Frontend tests failed. See log for details.
goto :fail

:sidecar_build_failed
echo [ERROR] Python sidecar build failed. >> "%LOGFILE%"
echo.
echo [FAILED] Sidecar PyInstaller build failed. See log for details.
goto :fail

:build_failed
echo [ERROR] npm run tauri:build:portable failed. >> "%LOGFILE%"
echo.
echo [FAILED] Desktop build failed. See log for details.
goto :fail

:missing_packaged_exe
echo [ERROR] Could not locate %PACKAGED_EXE_NAME% under src-tauri\target. >> "%LOGFILE%"
echo.
echo [FAILED] Build finished but the packaged exe was not found.
goto :fail

:copy_failed
echo [ERROR] Could not copy packaged exe to local_build. >> "%LOGFILE%"
echo.
echo [FAILED] Copy to local_build failed.
goto :fail

:selftest_failed
echo [ERROR] Packaged exe self-test failed. >> "%LOGFILE%"
echo.
echo [FAILED] Packaged exe self-test failed. See log for details.
goto :fail

:backend_selftest_failed
echo [ERROR] Packaged backend self-test failed. >> "%LOGFILE%"
echo.
echo [FAILED] Packaged backend self-test failed. See log for details.
goto :fail

:fail
echo.
echo ============================================================
echo   STATUS: FAILED
echo ============================================================
echo.
echo   Log:
echo   %LOGFILE%
echo.
popd
call :pause_if_needed
exit /b 1

:pause_if_needed
if "%NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0
