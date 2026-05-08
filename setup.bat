@echo off
echo ============================================
echo   ChatGPT to Word Agent - Setup
echo ============================================
echo.

echo [1/3] Installing Python packages...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed. Make sure Python is installed and in PATH.
    pause
    exit /b 1
)

echo.
echo [2/3] Installing Playwright Chromium browser...
playwright install chromium
if errorlevel 1 (
    echo ERROR: Playwright install failed.
    pause
    exit /b 1
)

echo.
echo [3/3] Checking for DISCORD_TOKEN...
if "%DISCORD_TOKEN%"=="" (
    echo WARNING: DISCORD_TOKEN environment variable is not set.
    echo Create a .env file in this folder with:
    echo   DISCORD_TOKEN=your_bot_token_here
    echo Or set it as a system environment variable.
) else (
    echo DISCORD_TOKEN found.
)

echo.
echo ============================================
echo   Setup complete!
echo   CLI mode:     python agent.py
echo   Discord mode: python discord_bot.py
echo ============================================
pause
