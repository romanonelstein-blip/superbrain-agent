@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  SuperBrain SB-023.2 Doctor
echo ============================================================
echo Folder: %CD%
echo.
where py >nul 2>&1 && (py -3 --version) || (python --version)
echo.
where node >nul 2>&1 && (node --version) || echo Node.js: NOT FOUND - required for model provider calls
echo.
if exist ".env" (echo .env: PRESENT) else (echo .env: MISSING)
if exist "integrations\superbrain_orchestrator_v2\dist\src\nexus-bridge-cli.js" (echo Provider bridge: PRESENT) else (echo Provider bridge: MISSING)
if exist "work\mission-control-url.txt" (
  echo.
  echo Last Mission Control URL:
  type "work\mission-control-url.txt"
)
echo.
echo Running local Python health tests...
where py >nul 2>&1 && (py -3 -m unittest tests.test_v028_mission_control tests.test_v031_sb023_e2e -q) || (python -m unittest tests.test_v028_mission_control tests.test_v031_sb023_e2e -q)
echo.
pause
endlocal
