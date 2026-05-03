@echo off
REM run.bat - one-click launcher for Lens on Windows.

setlocal

cd /d "%~dp0"

echo.
echo === Lens - starting up ===
echo.

REM Check Python
where python >nul 2>nul
if errorlevel 1 (
    echo [error] Python not found on PATH.
    echo Install from python.org or run: winget install Python.Python.3.12
    pause
    exit /b 1
)

REM Check the streamlit module is installed; install requirements if not.
python -c "import streamlit" >nul 2>nul
if errorlevel 1 (
    echo [setup] First run - installing Python dependencies...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [error] pip install failed.
        pause
        exit /b 1
    )
)

REM Launch Streamlit. It will open the browser automatically.
echo Opening Lens in your browser at http://localhost:8501
echo.
echo Press Ctrl+C in this window to stop the app.
echo.

python -m streamlit run app.py --server.headless false --browser.gatherUsageStats false

endlocal
