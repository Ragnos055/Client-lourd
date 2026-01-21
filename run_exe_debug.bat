@echo off
echo ============================================================
echo   DECENTRALIS CLIENT (.EXE) - MODE DEBUG
echo ============================================================
echo.

cd /d "%~dp0dist"

if not exist "decentralis-client.exe" (
    echo ERREUR: decentralis-client.exe non trouve!
    echo Lancez d'abord .\build_windows.ps1 pour compiler.
    pause
    exit /b 1
)

echo Lancement avec logging DEBUG...
echo Les logs s'afficheront dans cette console.
echo.

decentralis-client.exe --debug

pause
