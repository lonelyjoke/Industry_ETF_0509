@echo off
setlocal
cd /d "%~dp0\.."

echo ============================================================
echo A-share ETF rotation: local Tushare bridge
echo ============================================================
echo.
echo Keep this window open. Codex can then ask this local bridge
echo to fetch data and write caches under data\local_csv.
echo.

if "%TUSHARE_TOKEN%"=="" (
  set /p TUSHARE_TOKEN=Paste your TUSHARE_TOKEN and press Enter: 
)

if "%TUSHARE_API_URL%"=="" (
  set TUSHARE_API_URL=https://api.waditu.com/dataapi
)

python scripts\tushare_bridge.py
pause
