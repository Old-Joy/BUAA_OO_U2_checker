@echo off
echo Running Elevator Test Suite...
echo.

REM Ensure python is in PATH
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python does not seem to be installed or added to PATH.
    goto :eof
)

REM Check for colorama (optional but recommended)
python -c "import colorama" > nul 2>&1
if %errorlevel% neq 0 (
    echo Warning: colorama library not found. Output will be monochrome.
    echo You can install it using: pip install colorama
    echo.
)


REM Run the main Python test runner script
python run_test.py

echo.
echo Test suite finished.
pause