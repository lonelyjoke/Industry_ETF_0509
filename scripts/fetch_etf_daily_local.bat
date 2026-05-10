@echo off
setlocal
cd /d "%~dp0\.."

echo ============================================================
echo A-share ETF rotation: fetch ETF daily data with resume
echo ============================================================
echo.
echo This launcher runs in your own Windows terminal, outside the
echo Codex execution sandbox. It caches each ETF separately.
echo.

if "%TUSHARE_TOKEN%"=="" (
  set /p TUSHARE_TOKEN=Paste your TUSHARE_TOKEN and press Enter: 
)

if "%TUSHARE_API_URL%"=="" (
  set TUSHARE_API_URL=https://api.waditu.com/dataapi
)

python scripts\fetch_etf_daily.py
echo.
echo Done. Cached files are under data\local_csv.
pause
