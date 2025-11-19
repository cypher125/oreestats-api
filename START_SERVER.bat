@echo off
echo ============================================
echo Starting Oree Stats API Server
echo ============================================
echo.

REM Navigate to project directory
cd /d "%~dp0"

echo [1/4] Checking Python...
python --version
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.10+
    pause
    exit /b 1
)
echo.

echo [2/4] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo.

echo [3/4] Running database migrations...
python manage.py migrate
if errorlevel 1 (
    echo WARNING: Migrations failed. You may need to set up the database first.
    echo Continuing anyway...
)
echo.

echo [4/4] Starting Django server...
echo.
echo ============================================
echo Server will start at: http://localhost:8000
echo Swagger UI: http://localhost:8000/api/docs/
echo Press CTRL+C to stop the server
echo ============================================
echo.

python manage.py runserver
pause
