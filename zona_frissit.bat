@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 0/4 kezi korszakok (forras/kezi_korszak.csv)
py tenyek_kezi_korszak.py || goto hiba
echo === 1/4 osszeepit (zonak, gyenge evszamok eldobasa) ===
py osszeepit.py varos || goto hiba
echo === 2/4 ev_becsles (ez a leglassabb) ===
py ev_becsles.py varos || goto hiba
echo === 3/4 osszeepit (becsles es zonalinkek beirasa) ===
py osszeepit.py varos || goto hiba
echo === 4/4 csempek_keszites (3D-csempek) ===
py csempek_keszites.py varos || goto hiba
echo.
echo Kesz. Nyisd meg: http://localhost:8000/terkep3d/index.html  (Ctrl+Shift+R)
pause
exit /b 0
:hiba
echo.
echo HIBA: a fenti lepes nem sikerult, a tobbit nem futtattam.
pause
exit /b 1
