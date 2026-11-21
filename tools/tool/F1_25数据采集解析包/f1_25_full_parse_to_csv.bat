@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PY_SCRIPT=%SCRIPT_DIR%f1_25_full_parse_to_csv.py"

if not exist "%PY_SCRIPT%" (
    echo Parse script not found: "%PY_SCRIPT%"
    exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (
    pushd "%SCRIPT_DIR%"
    py -3 "%PY_SCRIPT%" %*
    set "EXIT_CODE=%errorlevel%"
    popd
    exit /b %EXIT_CODE%
)

where python >nul 2>nul
if %errorlevel%==0 (
    pushd "%SCRIPT_DIR%"
    python "%PY_SCRIPT%" %*
    set "EXIT_CODE=%errorlevel%"
    popd
    exit /b %EXIT_CODE%
)

echo Python 3 was not found. Install Python 3 and ensure "py" or "python" is in PATH.
exit /b 1
