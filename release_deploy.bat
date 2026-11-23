@echo off
chcp 65001 >nul
echo 1/2: a release mappa elkeszitese...
py build_release.py
if errorlevel 1 (
  echo HIBA a release keszitesekor, a feltoltes nem indul.
  pause
  exit /b 1
)
echo 2/2: feltoltes a Cloudflare-re...
call npx wrangler deploy
pause
