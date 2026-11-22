@echo off
chcp 65001 >nul
echo 1/2: a kiadas mappa elkeszitese...
py kiadas_keszites.py
if errorlevel 1 (
  echo HIBA a kiadas keszitesekor, a feltoltes nem indul.
  pause
  exit /b 1
)
echo 2/2: feltoltes a Cloudflare-re...
call npx wrangler deploy kiadas
pause
