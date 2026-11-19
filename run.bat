@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv || goto :error
)
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :error
".venv\Scripts\python.exe" -m app %*
goto :eof
:error
echo.
echo Setup failed. Make sure Python 3.10+ is installed and on PATH.
pause
