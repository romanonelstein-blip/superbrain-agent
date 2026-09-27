@echo off
setlocal
cd /d "%~dp0"
python scripts\verify_p0.py %*
set EXITCODE=%ERRORLEVEL%
echo.
echo verify_p0.py exit code: %EXITCODE%
exit /b %EXITCODE%
