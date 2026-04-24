@echo off
chcp 65001 >nul 2>&1
title Binance Scalping Bot

cd /d "%~dp0"

echo ============================================
echo   Binance Scalping Bot Launcher
echo ============================================
echo.

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.10+
    pause
    exit /b 1
)

:: Check .env exists
if not exist ".env" (
    echo [ERROR] .env file not found.
    echo         Copy .env.example to .env and add your API keys.
    pause
    exit /b 1
)

:: Install dependencies
echo [*] Checking dependencies...
pip install -r requirements.txt --quiet --break-system-packages 2>nul || pip install -r requirements.txt --quiet 2>nul
echo [OK] Dependencies ready.
echo.

:: Run bot in live mode (unbuffered output for live ticker)
echo [*] Starting bot in LIVE mode...
echo [*] Press Ctrl+C to stop.
echo.
python -u main.py --live

:: If bot exits
echo.
echo [*] Bot stopped.
pause
