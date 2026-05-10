@echo off
setlocal
cd /d "%~dp0\.."

echo ============================================================
echo A-share ETF rotation: local Tushare access check
echo ============================================================
echo.
echo This launcher runs in your own Windows terminal, outside the
echo Codex execution sandbox. It does not save your token to code.
echo.

if "%TUSHARE_TOKEN%"=="" (
  set /p TUSHARE_TOKEN=Paste your TUSHARE_TOKEN and press Enter: 
)

if "%TUSHARE_API_URL%"=="" (
  set TUSHARE_API_URL=https://api.waditu.com/dataapi
)

echo.
echo Python:
where python
echo.
echo TUSHARE_API_URL=%TUSHARE_API_URL%
echo.
echo Running network diagnostics...
python scripts\diagnose_tushare_network.py
echo.
echo Running Tushare permission check...
python scripts\check_tushare_access.py --refresh
echo.
echo Done. If it failed, copy the output above back to Codex.
pause
