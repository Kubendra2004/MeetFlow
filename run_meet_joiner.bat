@echo off
chcp 65001 > nul
title Google Meet Auto-Joiner v2
cd /d "k:\Project Programs\kubi\google meet joiner"

echo ================================================
echo   Google Meet Auto-Joiner v2
echo ================================================
echo.
echo   1. Run scheduler (waits for 1 PM)
echo   2. Join RIGHT NOW immediately
echo.
set /p choice="Enter 1 or 2: "

if "%choice%"=="2" (
    echo.
    echo [INFO] Joining immediately...
    start /BELOWNORMAL /wait cmd /c "chcp 65001 > nul && python meet_joiner.py --now"
) else (
    echo.
    echo [INFO] Running scheduler at BELOW NORMAL priority...
    echo [INFO] Press Ctrl+C to stop.
    start /BELOWNORMAL /wait cmd /c "chcp 65001 > nul && python meet_joiner.py"
)

echo.
echo [INFO] Bot has stopped.
pause
