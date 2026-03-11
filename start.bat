@echo off
echo ============================================
echo   ATMS - Advanced Training Management System
echo ============================================
echo.

REM Initialize database and seed data
python seed.py

echo.
echo Starting server...
echo Open http://localhost:8080 in your browser
echo Press Ctrl+C to stop
echo.
python server.py
pause
