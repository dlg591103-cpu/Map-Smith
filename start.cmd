@echo off
REM ============================================================
REM  MapSmith launcher for Windows (double-click to run).
REM  Kept ASCII-only on purpose: cmd.exe parses this file with the
REM  system codepage, so non-ASCII text and some symbols break it.
REM ============================================================
setlocal EnableExtensions
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "LOCK=%ROOT%src\requirements.lock"
set "PORT=8501"
set "URL=http://127.0.0.1:%PORT%"

title MapSmith

echo ==========================================
echo   MapSmith
echo   %URL%
echo ==========================================
echo.

if exist "%PY%" goto launch

echo [1/3] First run: looking for Python 3.12 ...
set "FOUND="

for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "C:\Python312\python.exe"
  "C:\Program Files\Python312\python.exe"
) do (
  if exist "%%~P" if not defined FOUND set "FOUND=%%~P"
)

if not defined FOUND (
  for /f "delims=" %%I in ('where python 2^>nul') do (
    echo %%I | findstr /i "WindowsApps" >nul
    if errorlevel 1 if not defined FOUND set "FOUND=%%I"
  )
)

if not defined FOUND (
  echo.
  echo [ERROR] Python 3.12 not found.
  echo.
  echo   Install from https://www.python.org/downloads/
  echo   IMPORTANT: tick "Add python.exe to PATH" during setup.
  echo.
  echo   Already installed elsewhere? Point at it manually:
  echo     set MAPSMITH_PYTHON=C:\path\to\python.exe
  echo     start.cmd
  echo.
  pause
  exit /b 1
)

echo       Using: %FOUND%
"%FOUND%" --version

echo [2/3] Creating .venv and installing dependencies...
echo       First run only. Takes about 2-5 minutes, please wait.
"%FOUND%" -m venv "%ROOT%.venv"
if errorlevel 1 (
  echo [ERROR] Failed to create .venv
  pause
  exit /b 1
)
if not exist "%PY%" (
  echo [ERROR] .venv created but python.exe is missing
  pause
  exit /b 1
)

echo       Installing packages (mirror)...
"%PY%" -m pip install --disable-pip-version-check -q -r "%LOCK%" -i https://repo.huaweicloud.com/repository/pypi/simple
if errorlevel 1 (
  echo       Mirror failed, retrying with default index...
  "%PY%" -m pip install --disable-pip-version-check -q -r "%LOCK%"
  if errorlevel 1 (
    echo [ERROR] Dependency install failed. Check network and retry.
    pause
    exit /b 1
  )
)
echo       Dependencies ready.

:launch
set "PYTHONPATH=%ROOT%src"
set "PYTHONIOENCODING=utf-8"

echo [3/3] Starting server...
start "MapSmith Server" /min "%PY%" -m mapsmith --host 127.0.0.1 --port %PORT%

set /a tries=0
:waitloop
set /a tries+=1
REM ping as a portable sleep: "timeout" fails when stdin is redirected.
ping -n 2 127.0.0.1 >nul 2>&1
powershell -NoProfile -Command "try{ Invoke-WebRequest -Uri '%URL%/api/health' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 }catch{ exit 1 }" >nul 2>&1
if not errorlevel 1 goto ready
if %tries% lss 90 goto waitloop

echo [WARN] Server did not become ready in 90s.
echo        Check the "MapSmith Server" window for the error message.
pause
exit /b 1

:ready
echo.
echo   Server is running. Opening browser...
start "" "%URL%"
echo.
echo   Tip: click "Settings API" in the left sidebar to configure keys.
echo   Keep this window open while using MapSmith.
echo   Press any key to STOP the server.
pause >nul

taskkill /FI "WINDOWTITLE eq MapSmith Server*" /F >nul 2>&1
echo Server stopped.
endlocal
