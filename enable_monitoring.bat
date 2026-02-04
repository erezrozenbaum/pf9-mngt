@echo off
echo.
echo 🔧 PF9 Monitoring Auto-Setup
echo.
echo This script automatically sets up monitoring after docker-compose up
echo.

REM Check if .env exists
if not exist ".env" (
    echo ❌ .env file not found. Please run: copy .env.template .env
    echo.
    pause
    exit /b 1
)

echo 📊 Setting up monitoring automation...
powershell -ExecutionPolicy Bypass -File "setup_monitoring_on_startup.ps1"

echo.
echo ✅ Monitoring setup complete!
echo.
echo 🌐 Open monitoring dashboard: http://localhost:5173
echo 📊 Check monitoring tab for real-time metrics
echo.
echo ℹ️  Next time, use startup.ps1 for complete automation
pause