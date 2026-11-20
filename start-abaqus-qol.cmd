@echo off
rem Abaqus QOL launcher for Windows.
rem
rem This batch file is an alternative to running scripts\serve.py from PowerShell,
rem so a machine with a restrictive execution policy can still start the workbench.
rem Any configuration such as SEAL_DATA or SIMPLIFY_ABAQUS_LAUNCHER set in the
rem environment before this file is called is inherited unchanged.

setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

if not exist "%ROOT%.venv\Scripts\python.exe" (
  echo Abaqus QOL: the Python environment is missing.
  echo Create it once from this folder:
  echo     py -3.11 -m venv .venv
  echo     .\.venv\Scripts\python -m pip install -r requirements.txt
  exit /b 1
)

if not exist "%ROOT%apps\web\dist\index.html" (
  echo Abaqus QOL: the browser build is missing.
  echo Build it once from this folder:
  echo     npm --prefix apps/web ci
  echo     npm --prefix apps/web run build
  exit /b 1
)

"%ROOT%.venv\Scripts\python.exe" "%ROOT%scripts\serve.py" %*
exit /b %ERRORLEVEL%
