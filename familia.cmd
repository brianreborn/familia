@echo off
rem familia on Windows: Charm/gum home by default; legacy menu via -LegacyMenu or "menu".
rem   familia.cmd                       gum home (Talk to the protomodel first)
rem   familia.cmd -LegacyMenu | menu    old catalog
rem   familia.cmd COMMAND ...           CLI (scripts\cli-commands.txt)
setlocal
if "%~1"=="" (
  if /I "%FAMILIA_LEGACY_MENU%"=="1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\familia-menu.ps1"
    exit /b %ERRORLEVEL%
  )
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\familia-home.ps1"
  exit /b %ERRORLEVEL%
)
if /I "%~1"=="-LegacyMenu" (
  shift
  set "FAMILIA_CLI_ARGS=%*"
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\familia-menu.ps1" -Cli
  exit /b %ERRORLEVEL%
)
if /I "%~1"=="--legacy-menu" (
  shift
  set "FAMILIA_CLI_ARGS=%*"
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\familia-menu.ps1" -Cli
  exit /b %ERRORLEVEL%
)
if /I "%~1"=="menu" (
  shift
  set "FAMILIA_CLI_ARGS=%*"
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\familia-menu.ps1" -Cli
  exit /b %ERRORLEVEL%
)
if /I "%~1"=="-Home" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\familia-home.ps1" %2 %3 %4 %5
  exit /b %ERRORLEVEL%
)
if /I "%~1"=="--home" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\familia-home.ps1" %2 %3 %4 %5
  exit /b %ERRORLEVEL%
)
set "FAMILIA_CLI_ARGS=%*"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\familia-menu.ps1" -Cli
exit /b %ERRORLEVEL%
