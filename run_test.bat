@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
setlocal
cd /d "%~dp0"

echo Test Resource:
echo   config\test_resources.yml
echo Test Capability:
echo   config\test_capabilities.yml
echo.

set TEST_CONFIG_ENABLED=true

where python >nul 2>nul
if errorlevel 1 (
    echo Python command not found.
    pause
    exit /b 2
)

python start.py
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" pause
exit /b %EXITCODE%
