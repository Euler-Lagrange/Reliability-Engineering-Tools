@echo off
if "%~1"=="__INNER__" goto :main
if /I "%~1"=="--no-pause" goto :outer_no_pause

cmd /k ""%~f0" __INNER__ %*"
exit /b %ERRORLEVEL%

:outer_no_pause
cmd /c ""%~f0" __INNER__ %*"
exit /b %ERRORLEVEL%

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
set "SIDECAR_EXE_NAME=reliability-tools-sidecar.exe"
set "BACKEND_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"

if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"

for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format \"yyyyMMdd_HHmmss\""') do set "TIMESTAMP=%%i"
if not defined TIMESTAMP set "TIMESTAMP=unknown_%RANDOM%"
set "LOGFILE=%LOGS_DIR%\release_%TIMESTAMP%.log"
set "RELEASE_STAGE_ROOT=%ROOT_DIR%\build\release_staging"
set "PAIR_STAGE=%RELEASE_STAGE_ROOT%\pair_%TIMESTAMP%_%RANDOM%"
set "STAGED_DESKTOP=%PAIR_STAGE%\ReliabilityToolsDesktop.exe"
set "STAGED_SIDECAR=%PAIR_STAGE%\%SIDECAR_EXE_NAME%"
set "OUTPUT_BACKUP=%RELEASE_STAGE_ROOT%\last_good_%TIMESTAMP%_%RANDOM%"

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

echo [1/16] Checking toolchain...
where node >nul 2>&1 || goto :missing_node
where npm >nul 2>&1 || goto :missing_npm

for /f "delims=" %%i in ('node --version 2^>nul') do set "NODE_VERSION=%%i"
echo [INFO] Detected Node !NODE_VERSION! >> "%LOGFILE%"
node -e "const [major, minor] = process.versions.node.split('.').map(Number); process.exit((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major >= 23 ? 0 : 1)" >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :unsupported_node_version

if not exist "%BACKEND_PYTHON%" goto :missing_backend_python
for /f "tokens=2" %%i in ('"%BACKEND_PYTHON%" --version 2^>^&1') do set "PYTHON_VERSION=%%i"
echo [INFO] Detected Python !PYTHON_VERSION! >> "%LOGFILE%"
"%BACKEND_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :unsupported_python_version
echo [INFO] Toolchain versions satisfy Node 20.19+ within major 20, or Node 22.12+; Python 3.11+. >> "%LOGFILE%"

echo [2/16] Checking version consistency...
call npm run version:check >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :version_check_failed

echo [3/16] Typechecking frontend...
call npm run typecheck >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :typecheck_failed

echo [4/16] Typechecking frontend tests...
call npm run typecheck:tests >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :typecheck_tests_failed

echo [5/16] Typechecking Rust bridge (cargo check)...
call npm run cargo:check >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :cargo_check_failed

echo [6/16] Running Rust bridge tests (cargo test)...
call npm run cargo:test >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :cargo_test_failed

echo [7/16] Running backend security audit...
pushd "%REPO_ROOT%\backend\python"
"%BACKEND_PYTHON%" -m common.security_audit --strict >> "%LOGFILE%" 2>&1
set "AUDIT_RC=%ERRORLEVEL%"
popd
if not "%AUDIT_RC%"=="0" goto :security_audit_failed

echo [8/16] Running backend tests...
"%BACKEND_PYTHON%" -m pytest backend\tests -q >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :backend_tests_failed

echo [9/16] Running frontend tests...
call npm test >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :tests_failed

echo [10/16] Building Python sidecar exe...
"%BACKEND_PYTHON%" scripts\build_sidecar.py --output-dir "%PAIR_STAGE%" >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :sidecar_build_failed

echo [11/16] Building portable desktop exe...
call npm run tauri:build:portable >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :build_failed

echo [12/16] Locating packaged executable...
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

REM Assemble the exact two-file release pair in run-specific staging. Release
REM builds resolve the sidecar exe-adjacent ONLY (never the dev tree), so both
REM packaged self-tests below exercise the files that will be promoted.
echo [13/16] Assembling staged desktop/sidecar pair...
if not exist "%STAGED_SIDECAR%" goto :missing_sidecar_exe
copy /y "%PACKAGED_EXE%" "%STAGED_DESKTOP%" >nul
if errorlevel 1 goto :stage_desktop_failed
echo [INFO] Staged release pair in %PAIR_STAGE% >> "%LOGFILE%"

REM Self-test the exact staged pair before promotion. local_build remains
REM untouched until both executables have passed every gate.
echo [14/16] Running packaged self-test...
"%STAGED_DESKTOP%" --self-test >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :selftest_failed

echo [15/16] Running packaged backend self-test...
"%STAGED_DESKTOP%" --self-test-backend >> "%LOGFILE%" 2>&1
if errorlevel 1 goto :backend_selftest_failed

REM The pair is the release unit. Rename the old directory to a run-specific
REM backup, move the verified staging directory into place, and roll the old
REM directory back if the second rename fails. Because all paths share the
REM repository volume, each directory move is a filesystem rename.
echo [16/16] Promoting verified pair to local_build...
set "PAIR_ENTRY_COUNT="
for /f %%i in ('dir /b /a "%PAIR_STAGE%" 2^>nul ^| find /c /v ""') do set "PAIR_ENTRY_COUNT=%%i"
if not "!PAIR_ENTRY_COUNT!"=="2" goto :invalid_pair_stage

set "HAD_LAST_GOOD=0"
if exist "%OUTPUT_BACKUP%" goto :backup_path_collision
if exist "%OUTPUT_DIR%" (
    move /y "%OUTPUT_DIR%" "%OUTPUT_BACKUP%" >nul
    if errorlevel 1 goto :backup_last_good_failed
    if exist "%OUTPUT_DIR%" goto :backup_last_good_failed
    if not exist "%OUTPUT_BACKUP%" goto :backup_last_good_failed
    set "HAD_LAST_GOOD=1"
)

move /y "%PAIR_STAGE%" "%OUTPUT_DIR%" >nul
if errorlevel 1 goto :promote_pair_failed
if not exist "%OUTPUT_EXE%" goto :promote_pair_failed
if not exist "%OUTPUT_DIR%\%SIDECAR_EXE_NAME%" goto :promote_pair_failed

if "!HAD_LAST_GOOD!"=="1" (
    rmdir /s /q "%OUTPUT_BACKUP%" >nul 2>&1
    if exist "%OUTPUT_BACKUP%" echo [WARN] Verified pair promoted, but old backup remains at %OUTPUT_BACKUP% >> "%LOGFILE%"
)
echo [INFO] Promoted verified desktop/sidecar pair to %OUTPUT_DIR% >> "%LOGFILE%"

echo.
echo ============================================================
echo   STATUS: SUCCESS
echo ============================================================
echo.
echo   Portable EXE:
echo   %OUTPUT_EXE%
echo.
echo   Python sidecar:
echo   %OUTPUT_DIR%\%SIDECAR_EXE_NAME%
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

:unsupported_node_version
echo [ERROR] Unsupported Node version !NODE_VERSION!. Required: Node 20.19+ within major 20, or Node 22.12+. >> "%LOGFILE%"
echo.
echo [FAILED] Node !NODE_VERSION! is unsupported.
echo          Install Node 20.19+ within major 20, or Node 22.12+.
goto :fail

:missing_backend_python
echo [ERROR] Could not find backend Python at %BACKEND_PYTHON%. >> "%LOGFILE%"
echo.
echo [FAILED] Backend Python interpreter was not found.
goto :fail

:unsupported_python_version
echo [ERROR] Unsupported Python version !PYTHON_VERSION!. Required: Python 3.11 or newer. >> "%LOGFILE%"
echo.
echo [FAILED] Python !PYTHON_VERSION! is unsupported.
echo          Recreate .venv with Python 3.11 or newer.
goto :fail

:version_check_failed
echo [ERROR] Version consistency check (bump-version --check) failed. >> "%LOGFILE%"
echo.
echo [FAILED] Version numbers are out of sync across manifests. See log for details.
goto :fail

:typecheck_failed
echo [ERROR] Frontend typecheck (tsc) reported errors. >> "%LOGFILE%"
echo.
echo [FAILED] Frontend typecheck failed. See log for details.
goto :fail

:typecheck_tests_failed
echo [ERROR] Frontend test typecheck (tsc) reported errors. >> "%LOGFILE%"
echo.
echo [FAILED] Frontend test typecheck failed. See log for details.
goto :fail

:cargo_check_failed
echo [ERROR] Rust bridge `cargo check` reported errors. >> "%LOGFILE%"
echo.
echo [FAILED] Rust bridge did not typecheck. See log for details.
goto :fail

:cargo_test_failed
echo [ERROR] Rust bridge `cargo test` reported failures. >> "%LOGFILE%"
echo.
echo [FAILED] Rust bridge tests failed. See log for details.
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

:missing_sidecar_exe
echo [ERROR] Could not find the staged sidecar at %STAGED_SIDECAR%. >> "%LOGFILE%"
echo.
echo [FAILED] Bundled sidecar exe was not found for staging.
goto :fail

:stage_desktop_failed
echo [ERROR] Could not copy the packaged desktop to %STAGED_DESKTOP%. >> "%LOGFILE%"
echo.
echo [FAILED] Assembling the staged desktop/sidecar pair failed.
goto :fail

:invalid_pair_stage
echo [ERROR] Staged release directory must contain exactly the two expected executables. >> "%LOGFILE%"
echo [ERROR] Found !PAIR_ENTRY_COUNT! entries under %PAIR_STAGE%. >> "%LOGFILE%"
echo.
echo [FAILED] Staged release pair validation failed. See log for details.
goto :fail

:backup_path_collision
echo [ERROR] Refusing to overwrite unexpected backup path %OUTPUT_BACKUP%. >> "%LOGFILE%"
echo.
echo [FAILED] Release backup path already exists. Re-run the release.
goto :fail

:backup_last_good_failed
echo [ERROR] Could not move the current local_build directory to %OUTPUT_BACKUP%. >> "%LOGFILE%"
if not exist "%OUTPUT_DIR%" if exist "%OUTPUT_BACKUP%" move /y "%OUTPUT_BACKUP%" "%OUTPUT_DIR%" >nul
echo.
echo [FAILED] Could not secure the last-good pair before promotion.
goto :fail

:promote_pair_failed
echo [ERROR] Could not move the verified staged pair into %OUTPUT_DIR%. >> "%LOGFILE%"
if exist "%OUTPUT_DIR%" (
    if exist "%PAIR_STAGE%" goto :pair_rollback_failed
    move /y "%OUTPUT_DIR%" "%PAIR_STAGE%" >nul
    if errorlevel 1 goto :pair_rollback_failed
)
if "!HAD_LAST_GOOD!"=="1" (
    move /y "%OUTPUT_BACKUP%" "%OUTPUT_DIR%" >nul
    if errorlevel 1 goto :pair_rollback_failed
)
echo [INFO] Restored the previous last-good pair after promotion failure. >> "%LOGFILE%"
echo.
echo [FAILED] Pair promotion failed; the previous local_build was restored.
goto :fail

:pair_rollback_failed
echo [ERROR] Automatic rollback failed. The intact last-good pair remains at %OUTPUT_BACKUP%. >> "%LOGFILE%"
echo.
echo [FAILED] Pair promotion and automatic rollback failed.
echo          The prior pair remains intact at:
echo          %OUTPUT_BACKUP%
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
call :cleanup_staging
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

:cleanup_staging
if not defined PAIR_STAGE exit /b 0
if /I "%PAIR_STAGE%"=="%RELEASE_STAGE_ROOT%" exit /b 1
if exist "%PAIR_STAGE%" rmdir /s /q "%PAIR_STAGE%" >nul 2>&1
exit /b 0
