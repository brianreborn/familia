@echo off
rem familia on Windows: the same commands as ./familia (scripts\cli-commands.txt, scripts\menu-items.txt).
rem   familia.cmd                       the menu
rem   familia.cmd help [COMMAND]        every command, or what one runs
rem   familia.cmd COMMAND [VALUE...] [ARG...]   e.g.  familia.cmd skills list   familia.cmd --dry-run model params coder
rem   familia.cmd -List / -Run KEY [ARG...] / -Search WORD [-Run N]   (older flags, still work; -DryRun, -Yes, -Pipe)
setlocal
set "FAMILIA_CLI_ARGS=%*"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\familia-menu.ps1" -Cli
exit /b %ERRORLEVEL%
