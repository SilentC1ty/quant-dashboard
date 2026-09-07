@echo off
setlocal

cd /d "%~dp0"

echo ========================================
echo   Quant Dashboard

echo   Project: %CD%
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found:
    echo         %CD%\.venv
    echo.
    echo Please create it first with:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -e .
    echo.
    pause
    exit /b 1
)

if not exist "app.py" (
    echo [ERROR] app.py not found in %CD%
    echo.
    pause
    exit /b 1
)

echo Starting Quant Dashboard...
echo Close this window or press Ctrl+C to stop it.
echo.

".venv\Scripts\python.exe" -m streamlit run app.py

if errorlevel 1 (
    echo.
    echo [ERROR] Dashboard stopped with an error.
    echo.
    pause
)

endlocal
