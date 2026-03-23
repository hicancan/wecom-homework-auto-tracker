@echo off
setlocal
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
set "RUNNER_PY=%SCRIPT_DIR%run_extract_interactive.py"

if not exist "%RUNNER_PY%" (
  echo [ERROR] Script not found: %RUNNER_PY%
  pause
  exit /b 1
)

set "PYTHON_EXE=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  where python >nul 2>nul
  if %ERRORLEVEL%==0 (
    set "PYTHON_EXE=python"
  ) else (
    echo [ERROR] Python not found. Please install Python or create .venv first.
    pause
    exit /b 1
  )
)

"%PYTHON_EXE%" "%RUNNER_PY%" %*

set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
  echo Failed with exit code: %EXIT_CODE%
) else (
  echo Completed.
)
pause
exit /b %EXIT_CODE%

