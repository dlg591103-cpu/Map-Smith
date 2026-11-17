@echo off
setlocal EnableDelayedExpansion
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

title MapSmith Data Warmup
chcp 65001 >nul

echo ==============================================
echo   MapSmith - Download daily air data (warmup)
echo   Source: quotsoft.net
echo ==============================================
echo.

if not exist "%PY%" (
    echo [ERROR] venv not found: %PY%
    echo Run "start-mapsmith.cmd" once first to create it.
    pause
    exit /b 1
)

echo Download the last N days ^(default 7^).
echo Data is cached into: src\mapsmith\demo_data\air\
echo.
set /p DAYS=How many days? [7]:
if "%DAYS%"=="" set "DAYS=7"

echo.
echo === Downloading... ===
"%PY%" "%ROOT%warmup_data.py" --days %DAYS%
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo === Done. All dates cached. ===
) else (
    echo === Finished with some failures, see log above. ===
)
echo.
echo Tip: keep "start-mapsmith.cmd" in OFFLINE mode for the demo.
echo.
pause
endlocal
