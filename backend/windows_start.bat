@echo off
:: Life Manager Backend — Windows Startup Script
:: Run this once to start the backend, or register it with Task Scheduler via windows_setup.ps1

cd /d "%~dp0"

:: Activate venv if it exists, otherwise use system Python
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [Life Manager] No venv found, using system Python
)

echo [Life Manager] Starting backend on port 8000...
python main.py
