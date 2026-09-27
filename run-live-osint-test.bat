@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem SuperBrain SB-027.1 — resilient live OSINT test launcher.
rem It works from a fully extracted folder and also detects the common Windows
rem mistake of running the BAT directly from inside a ZIP preview.

cd /d "%~dp0"
set PYTHONUTF8=1
set SUPERBRAIN_AUTO_START_TOR=1
set SUPERBRAIN_TOR_STARTUP_WAIT_SECONDS=45
set "SB_ROOT=%~dp0"
set "SB_SCRIPT=%~dp0live_osint_smoke_test.py"

if not exist "%SB_SCRIPT%" (
  echo.
  echo ============================================================
  echo  SuperBrain SB-027.1 - LIVE OSINT / EGRESS TEST
  echo ============================================================
  echo.
  echo The test script is not present in the current extracted folder.
  echo This usually means Windows is running this BAT directly from
  echo inside the ZIP instead of from an extracted folder.
  echo.
  echo Attempting automatic recovery from a downloaded SuperBrain ZIP...
  echo.

  set "SB_RECOVERED_ROOT="
  for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand JABFAHIAcgBvAHIAQQBjAHQAaQBvAG4AUAByAGUAZgBlAHIAZQBuAGMAZQA9ACcAUwBpAGwAZQBuAHQAbAB5AEMAbwBuAHQAaQBuAHUAZQAnAAoAJABuAGEAbQBlAD0AJwBTAHUAcABlAHIAQgByAGEAaQBuAC0AdgAwAC4AMQA3AC0AUwBCADAAMgA3AC0AdwBvAHIAbABkAC0AbQBvAGQAZQBsAC0AbwBzAGkAbgB0ACcACgAkAHIAbwBvAHQAcwA9AEAAKABbAEUAbgB2AGkAcgBvAG4AbQBlAG4AdABdADoAOgBHAGUAdABGAG8AbABkAGUAcgBQAGEAdABoACgAJwBEAG8AdwBuAGwAbwBhAGQAcwAnACkALABbAEUAbgB2AGkAcgBvAG4AbQBlAG4AdABdADoAOgBHAGUAdABGAG8AbABkAGUAcgBQAGEAdABoACgAJwBEAGUAcwBrAHQAbwBwACcAKQAsAFsARQBuAHYAaQByAG8AbgBtAGUAbgB0AF0AOgA6AEcAZQB0AEYAbwBsAGQAZQByAFAAYQB0AGgAKAAnAE0AeQBEAG8AYwB1AG0AZQBuAHQAcwAnACkALAAkAGUAbgB2ADoAVABFAE0AUAApACAAfAAgAFcAaABlAHIAZQAtAE8AYgBqAGUAYwB0ACAAewAkAF8AIAAtAGEAbgBkACAAKABUAGUAcwB0AC0AUABhAHQAaAAgACQAXwApAH0ACgAkAHoAPQBHAGUAdAAtAEMAaABpAGwAZABJAHQAZQBtACAALQBQAGEAdABoACAAJAByAG8AbwB0AHMAIAAtAEYAaQBsAHQAZQByACAAKAAkAG4AYQBtAGUAKwAnACoALgB6AGkAcAAnACkAIAAtAEYAaQBsAGUAIAAtAFIAZQBjAHUAcgBzAGUAIAAtAEUAcgByAG8AcgBBAGMAdABpAG8AbgAgAFMAaQBsAGUAbgB0AGwAeQBDAG8AbgB0AGkAbgB1AGUAIAB8ACAAUwBvAHIAdAAtAE8AYgBqAGUAYwB0ACAATABhAHMAdABXAHIAaQB0AGUAVABpAG0AZQAgAC0ARABlAHMAYwBlAG4AZABpAG4AZwAgAHwAIABTAGUAbABlAGMAdAAtAE8AYgBqAGUAYwB0ACAALQBGAGkAcgBzAHQAIAAxAAoAaQBmACgALQBuAG8AdAAgACQAegApAHsAZQB4AGkAdAAgADIAfQAKACQAZABlAHMAdAA9AEoAbwBpAG4ALQBQAGEAdABoACAAJABlAG4AdgA6AFQARQBNAFAAIAAoACQAbgBhAG0AZQArACcALQByAGUAYwBvAHYAZQByAGUAZAAnACkACgBpAGYAKABUAGUAcwB0AC0AUABhAHQAaAAgACQAZABlAHMAdAApAHsAUgBlAG0AbwB2AGUALQBJAHQAZQBtACAAJABkAGUAcwB0ACAALQBSAGUAYwB1AHIAcwBlACAALQBGAG8AcgBjAGUAIAAtAEUAcgByAG8AcgBBAGMAdABpAG8AbgAgAFMAaQBsAGUAbgB0AGwAeQBDAG8AbgB0AGkAbgB1AGUAfQAKAEUAeABwAGEAbgBkAC0AQQByAGMAaABpAHYAZQAgAC0ATABpAHQAZQByAGEAbABQAGEAdABoACAAJAB6AC4ARgB1AGwAbABOAGEAbQBlACAALQBEAGUAcwB0AGkAbgBhAHQAaQBvAG4AUABhAHQAaAAgACQAZABlAHMAdAAgAC0ARgBvAHIAYwBlAAoAJABzAD0ARwBlAHQALQBDAGgAaQBsAGQASQB0AGUAbQAgAC0AUABhAHQAaAAgACQAZABlAHMAdAAgAC0ARgBpAGwAdABlAHIAIAAnAGwAaQB2AGUAXwBvAHMAaQBuAHQAXwBzAG0AbwBrAGUAXwB0AGUAcwB0AC4AcAB5ACcAIAAtAEYAaQBsAGUAIAAtAFIAZQBjAHUAcgBzAGUAIAB8ACAAUwBlAGwAZQBjAHQALQBPAGIAagBlAGMAdAAgAC0ARgBpAHIAcwB0ACAAMQAKAGkAZgAoAC0AbgBvAHQAIAAkAHMAKQB7AGUAeABpAHQAIAAzAH0ACgAkAHMALgBEAGkAcgBlAGMAdABvAHIAeQBOAGEAbQBlAAoA`) do set "SB_RECOVERED_ROOT=%%I"

  if defined SB_RECOVERED_ROOT (
    set "SB_ROOT=!SB_RECOVERED_ROOT!\"
    set "SB_SCRIPT=!SB_RECOVERED_ROOT!\live_osint_smoke_test.py"
    echo Recovery succeeded.
    echo Running recovered test from:
    echo !SB_RECOVERED_ROOT!
    echo.
  ) else (
    echo.
    echo ERROR: Could not recover the test script automatically.
    echo.
    echo Please right-click the ZIP and choose ^"Extract All...^".
    echo Then open the extracted SuperBrain folder and run this BAT again.
    echo.
    pause
    exit /b 2
  )
)

echo ============================================================
echo  SuperBrain SB-027.1 - LIVE OSINT / EGRESS TEST
echo ============================================================
echo.
echo This test never prints credential values.
echo It tests GitHub + DuckDuckGo through the configured egress.
echo It also auto-detects a local Tor SOCKS proxy and tests Tor separately.
echo If Tor Browser is installed, the test will try to start it automatically.
echo A safe DuckDuckGo onion service is used automatically for the Tor onion smoke test.
echo.

pushd "%SB_ROOT%" >nul 2>&1
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  py -3 "%SB_SCRIPT%"
) else (
  python "%SB_SCRIPT%"
)
set "CODE=%ERRORLEVEL%"
popd >nul 2>&1

echo.
if "%CODE%" EQU "0" (
  echo LIVE TEST PASSED.
) else (
  echo LIVE TEST FAILED. Copy the output above; no secret values are included.
)
pause
exit /b %CODE%
