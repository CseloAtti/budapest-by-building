@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Cleanup (review, section e). Run it in the project folder: double-click or  takaritas.bat
rem It deletes only the files of the approved points A, B, C, then (E) removes the generated / large files from Git
rem without deleting them from your computer. It does NOT commit and does NOT push.
echo Ez a szkript torli az atvilagitasban jovahagyott felesleges fajlokat.
echo Megszakitas: Ctrl+C.   Folytatas:
pause

echo === A) biztosan felesleges fajlok
for %%F in (hello.py elemzes.py cimek.py diagnosztika.py letolt.py foltozas.py geojson_keszites.py.bak varos_osszeallitas.py.bak "forras\prioritas.json.bak" "forras\telepulesmagok.bak.json" "forras\zona_elvetett.bak.json" "forras\zonak_poligon.bak.geojson") do (
  if exist %%F ( del /q %%F && echo   torolve: %%F )
)
for %%D in (__pycache__ "tesztek\__pycache__" mentes_7korszak) do (
  if exist %%D ( rmdir /s /q %%D && echo   torolve: %%D\ )
)

echo === B) B-becsles / eltereskep es telepulesmagok (a forras\telepulesmagok.json MEGMARAD)
for %%F in (ev_becsles_ksh.py ksh_osszevetes.py magok.html magok_helye.py "data\varos\ev_becsles_ksh.csv" "data\varos\ev_becsles_ksh_jelentes.md" "data\varos\ev_becsles_eltereshelyek.csv" "data\varos\ksh_osszevetes.md" "data\magok_javaslat.csv") do (
  if exist %%F ( del /q %%F && echo   torolve: %%F )
)
for %%D in ("terkep3d\data_varos_ksh" "terkep3d\data_varos_elteres") do (
  if exist %%D ( rmdir /s /q %%D && echo   torolve: %%D\ )
)

echo === C) a regi belvarosi valtozat
for %%F in (geojson_keszites.py "data\belvaros_epuletek.json" "data\belvaros_epuletek.geojson" "data\belvaros_epuletek_vegleges.geojson" "data\belvaros_epuletek_lechner.geojson" "data\belvaros_reszek.geojson" "data\ev_becsles.csv" "data\ev_becsles_jelentes.md" "data\ev_becsles_munkalista.csv") do (
  if exist %%F ( del /q %%F && echo   torolve: %%F )
)
if exist "terkep3d\data" ( rmdir /s /q "terkep3d\data" && echo   torolve: terkep3d\data\ )

echo === E) Git: generalt es nagy fajlok kivetele a tarolobol (a gepeden megmaradnak)
where git >nul 2>nul
if errorlevel 1 (
  echo   Nincs git a gepen: ezt a lepest kihagytam.
) else (
  git rm -r --cached --quiet --ignore-unmatch data __pycache__ "tesztek/__pycache__" mentes_7korszak terkep3d/data terkep3d/data_varos terkep3d/data_varos_ksh terkep3d/data_varos_elteres "*.bak" "*.bak.json" "*.bak.geojson"
  git rm --cached --quiet --ignore-unmatch hello.py elemzes.py cimek.py diagnosztika.py letolt.py foltozas.py geojson_keszites.py ev_becsles_ksh.py ksh_osszevetes.py magok.html magok_helye.py
  echo   Kesz. Ellenorzes:  git status
)
echo.
echo Kesz. Utana futtasd:  py tesztek\futtat_mindent.py
pause
