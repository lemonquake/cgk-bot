@echo off
:: CGK Linens Discord Bot Launcher (Windows)
:: Created by Aljay Leodones for CGK Linens

cd /d "%~dp0"
title CGK Linens Discord Bot

echo ==========================================
echo  Starting CGK Linens Discord Bot
echo  Created by Aljay Leodones
echo ==========================================

:: Check if virtual environment exists
if not exist "venv" (
    echo [1/3] Creating Python virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo Error: Failed to create virtual environment. Ensure Python 3 is installed and added to PATH.
        pause
        exit /b %errorlevel%
    )
)

:: Activate virtual environment
call venv\Scripts\activate.bat

:: Ensure dependencies are installed
echo [2/3] Checking dependencies...
pip install -r requirements.txt --quiet

:: Launch bot
echo [3/3] Launching bot...
python main.py

:: Keep window open if bot stops
echo.
echo Bot process has stopped.
pause
