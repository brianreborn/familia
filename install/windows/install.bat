@echo off
rem familia one-click Windows installer wrapper: double-click, or pass flags
rem (e.g. install.bat -DryRun, install.bat -Uninstall). No admin needed.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set RC=%ERRORLEVEL%
if "%~1"=="" pause
exit /b %RC%
