@echo off
rem Abaqus QOL launcher for Windows.
rem
rem Double-click this file (or call it with optional flags such as --port 8766).
rem It prepares the repository-local Python environment and browser bundle when
rem Python 3.11+ and Node.js are installed, starts the workbench and worker,
rem waits for /api/health, and opens the default browser. A second launch reuses
rem an instance that is already running instead of starting another worker.
rem Any configuration set in the environment (SEAL_DATA, SEAL_ODA,
rem SIMPLIFY_ABAQUS_LAUNCHER and their ABAQUS_QOL_* aliases) is inherited.
rem A restrictive PowerShell execution policy does not affect this file.

setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

if exist "%ROOT%.venv\Scripts\python.exe" goto project_python

rem No repository environment yet. Find a bootstrap interpreter once; serve.py
rem creates .venv, installs the pinned dependencies and builds the bundle.
where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,11) else 1)" >nul 2>nul
  if not errorlevel 1 goto py311
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,11) else 1)" >nul 2>nul
  if not errorlevel 1 goto py3
)

where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,11) else 1)" >nul 2>nul
  if not errorlevel 1 goto path_python
)

echo.
echo Abaqus QOL: Python 3.11 or newer was not found.
echo Install Python from https://www.python.org/downloads/ and tick
echo "Add python.exe to PATH", then run this file again.
echo.
echo Alternatively create the environment once from this folder:
echo     py -3.11 -m venv .venv
echo     .\.venv\Scripts\python -m pip install -r requirements.txt
echo     npm --prefix apps/web ci
echo     npm --prefix apps/web run build
echo.
set "launch_result=1"
goto report

:project_python
"%ROOT%.venv\Scripts\python.exe" "%ROOT%scripts\serve.py" %*
goto finished

:py311
py -3.11 "%ROOT%scripts\serve.py" %*
goto finished

:py3
py -3 "%ROOT%scripts\serve.py" %*
goto finished

:path_python
python "%ROOT%scripts\serve.py" %*

:finished
set "launch_result=%ERRORLEVEL%"
:report
rem Keep a failed double-click readable. Invocations with flags return immediately.
if not "%launch_result%"=="0" if "%~1"=="" pause
exit /b %launch_result%
