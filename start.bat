@echo off
title Discord Translation Bot
echo --------------------------------------------------
echo [1/2] Checking environment variables...
if not exist .env (
    echo [ERROR] .env file not found! 
    echo Please create .env file based on .env.example
    pause
    exit /b
)

echo [2/2] Starting the bot...
echo --------------------------------------------------
python bot.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Bot crashed with exit code %errorlevel%
    pause
)
