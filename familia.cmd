@echo off
rem familia: the menu on Windows (same items as ./familia-menu.sh). Flags: -List, -Run KEY [ARG...], -DryRun, -Yes, -Pipe
rem Example: familia.cmd -Run skills.list
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\familia-menu.ps1" %*
exit /b %ERRORLEVEL%
