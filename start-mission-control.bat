@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

echo.
echo ============================================================
echo  SuperBrain SB-027 - WORLD MODEL + OSINT Mission Control
echo ============================================================
echo  This launcher closes stale SuperBrain Mission Control servers,
echo  starts this exact build on a fresh port and opens that URL.
echo.

if not exist "work" mkdir "work"
if not exist ".env" (
  if exist ".env.example" copy /Y ".env.example" ".env" >nul
  echo Created .env from .env.example.
)

rem Stop only older SuperBrain Mission Control Python processes, not arbitrary Python apps.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'nexus1000[.]sb022_server' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  set "PY_CMD=py -3"
) else (
  where python >nul 2>&1
  if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python 3 was not found.
    echo Install Python 3.11 or newer, then run this file again.
    pause
    exit /b 1
  )
  set "PY_CMD=python"
)

echo Starting SuperBrain... Do not close this window while using Mission Control.
echo.
%PY_CMD% -m nexus1000.sb022_server --host 127.0.0.1 --port 0 --database "%CD%\work\superbrain-state.db" --open-browser

if %ERRORLEVEL% NEQ 0 (
  echo.
  echo SuperBrain stopped with an error.
  echo Run superbrain-doctor.bat and copy the result if you need help.
  pause
)
endlocal
