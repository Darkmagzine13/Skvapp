@echo off
title School Payroll - Local Flask Server

cd /d "%~dp0"

echo ==========================================
echo       SCHOOL PAYROLL SYSTEM
echo ==========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found.
    echo.
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Python could not create the virtual environment.
        echo Please make sure Python is installed.
        pause
        exit /b 1
    )
)

echo Activating virtual environment...
call ".venv\Scripts\activate.bat"

echo.
echo Installing/updating required packages...
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ERROR: Could not install the required packages.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo Starting School Payroll...
echo ==========================================
echo.
echo Open your browser at:
echo http://localhost:5000
echo.
echo Press CTRL+C to stop the server.
echo.

python app.py

pause