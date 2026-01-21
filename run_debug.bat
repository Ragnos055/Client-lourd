@echo off
echo ============================================================
echo   DECENTRALIS CLIENT - MODE DEBUG
echo ============================================================
echo.

cd /d "%~dp0src\decentralis-client"

echo Lancement avec logging DEBUG...
echo.

python main.py --debug

pause
