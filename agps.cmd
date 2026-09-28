@echo off
rem AzerothGPS dev launcher: runs the app in its own environment, from any folder.
rem   agps watch            agps serve            agps --help
rem First time (or after deleting the environment): agps setup
setlocal
set "VENV=%USERPROFILE%\.venvs\azerothgps"
set "PY=%VENV%\Scripts\python.exe"

if /i "%~1"=="setup" (
  if not exist "%PY%" python -m venv "%VENV%" || exit /b 1
  "%PY%" -m pip install --upgrade pip
  "%PY%" -m pip install -e "%~dp0app[dev]"
  exit /b %ERRORLEVEL%
)

if not exist "%PY%" (
  echo AzerothGPS environment not found at %VENV%
  echo Run:  "%~f0" setup
  exit /b 1
)

rem -P: don't put the current folder on sys.path (a folder named "azerothgps"
rem there would otherwise shadow the installed package).
"%PY%" -P -m azerothgps %*
