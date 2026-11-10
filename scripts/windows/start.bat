@echo off
rem familia: Windows launcher for one llama-server node (qodesh). See docs/windows.md (#17).
rem No AVX required: the official ggml-org Windows CPU build picks its CPU backend at
rem runtime and ran on qodesh's Athlon II X2 (SSE only, no AVX) on 2026-10-09.
rem
rem Settings (environment variables, all optional except a model):
rem   FAMILIA_MODELS     models dir   (default: E:\temp\familia\models if E:\temp exists, else %USERPROFILE%\familia\models)
rem   FAMILIA_MODEL      GGUF file name inside FAMILIA_MODELS, or a full path
rem   FAMILIA_RUNTIME    dir holding llama-server.exe (default: %~dp0..\..\runtime)
rem   FAMILIA_PORT       default 9941      FAMILIA_BIND  default 127.0.0.1
rem   FAMILIA_CTX        default 4096      FAMILIA_THREADS default 2
rem   FAMILIA_KV         default q8_0      FAMILIA_EXTRA  extra llama-server args
rem   FAMILIA_API_KEY_FILE  0600 key file (default: %APPDATA%\familia\instances\<port>\api-keys)
rem API key is required on every bind, loopback included (DESIGN.md Security).
rem Nothing here edits the graph; values should match the node in graph.yaml.
setlocal EnableExtensions

if not defined FAMILIA_MODELS (
  if exist "E:\temp\" ( set "FAMILIA_MODELS=E:\temp\familia\models" ) else ( set "FAMILIA_MODELS=%USERPROFILE%\familia\models" )
)
if not defined FAMILIA_RUNTIME set "FAMILIA_RUNTIME=%~dp0..\..\runtime"
if not defined FAMILIA_PORT set "FAMILIA_PORT=9941"
if not defined FAMILIA_BIND set "FAMILIA_BIND=127.0.0.1"
if not defined FAMILIA_CTX set "FAMILIA_CTX=4096"
if not defined FAMILIA_THREADS set "FAMILIA_THREADS=2"
if not defined FAMILIA_KV set "FAMILIA_KV=q8_0"

if /i "%~1"=="--help" goto :help
if /i "%~1"=="-h" goto :help
if /i "%~1"=="/?" goto :help
if not defined FAMILIA_MODEL (
  echo familia: set FAMILIA_MODEL to a GGUF in "%FAMILIA_MODELS%" first. Example: set FAMILIA_MODEL=qwen2.5-0.5b-instruct-q4_0.gguf 1>&2
  exit /b 2
)
rem An absolute FAMILIA_MODEL (C:\..., \\server\..., \...) is used as-is; a bare name is
rem resolved inside FAMILIA_MODELS. Never prefix the models dir onto a full path (#17).
set "MODEL=%FAMILIA_MODEL%"
set "M_ABS="
if "%FAMILIA_MODEL:~1,1%"==":" set "M_ABS=1"
if "%FAMILIA_MODEL:~0,1%"=="\" set "M_ABS=1"
if "%FAMILIA_MODEL:~0,1%"=="/" set "M_ABS=1"
if not defined M_ABS set "MODEL=%FAMILIA_MODELS%\%FAMILIA_MODEL%"
if not exist "%MODEL%" (
  echo familia: model not found: %MODEL% 1>&2
  exit /b 2
)
rem Licenses before anything runs (docs\licenses.md). FAMILIA_ACCEPT_LICENSES=yes is the non-interactive answer.
where python >nul 2>&1
if not errorlevel 1 (
  python "%~dp0..\licenses.py" gate
  if errorlevel 1 (
    echo familia: licenses not accepted; nothing started. Review: python "%~dp0..\licenses.py" review 1>&2
    exit /b 1
  )
  rem Pinned parts first, all together (scripts\sync_pins.py).
  python "%~dp0..\sync_pins.py" --auto
  if errorlevel 1 (
    echo familia: the pinned parts could not be synced ^(see above^); nothing started 1>&2
    exit /b 1
  )
) else (
  if /i not "%FAMILIA_ACCEPT_LICENSES%"=="yes" (
    echo familia: python not found, so the license review can't run. Install Python 3, or read docs\licenses.md and set FAMILIA_ACCEPT_LICENSES=yes 1>&2
    exit /b 2
  )
)
set "BIN=%FAMILIA_RUNTIME%\llama-server.exe"
if not exist "%BIN%" (
  echo familia: llama-server.exe not found in "%FAMILIA_RUNTIME%" ^(unzip llama-*-bin-win-cpu-x64.zip there^) 1>&2
  exit /b 2
)

if not exist "%FAMILIA_MODELS%\..\logs" mkdir "%FAMILIA_MODELS%\..\logs" >nul 2>&1
set "LOG=%FAMILIA_MODELS%\..\logs\llama-server-%FAMILIA_PORT%.log"
if not defined FAMILIA_API_KEY_FILE (
  if defined APPDATA (
    set "FAMILIA_API_KEY_FILE=%APPDATA%\familia\instances\%FAMILIA_PORT%\api-keys"
  ) else (
    set "FAMILIA_API_KEY_FILE=%USERPROFILE%\familia\instances\%FAMILIA_PORT%\api-keys"
  )
)
rem Refuse FAMILIA_EXTRA tokens that would override bind/port/auth/TLS/path (same rule as familia-start).
for %%T in (%FAMILIA_EXTRA%) do (
  echo %%T| findstr /i /b /c:"--host" /c:"--port" /c:"--api-key" /c:"--ssl" /c:"--path" >nul
  if not errorlevel 1 (
    echo familia: token %%T in FAMILIA_EXTRA would override bind/port/auth/TLS/path; refusing 1>&2
    exit /b 2
  )
)
where python >nul 2>&1
if errorlevel 1 (
  echo familia: python not found, so the API key file cannot be created or checked. Install Python 3. 1>&2
  exit /b 2
)
python "%~dp0..\bind_auth_guard.py" --ensure -- "%BIN%" -m "%MODEL%" --host "%FAMILIA_BIND%" --port "%FAMILIA_PORT%" --api-key-file "%FAMILIA_API_KEY_FILE%" %FAMILIA_EXTRA%
if errorlevel 1 (
  echo familia: auth guard refused this launch (API key required on every bind, loopback included) 1>&2
  exit /b 2
)
echo familia: %BIN% -m "%MODEL%" on %FAMILIA_BIND%:%FAMILIA_PORT% (log %LOG%)
"%BIN%" -m "%MODEL%" --host "%FAMILIA_BIND%" --port "%FAMILIA_PORT%" -c %FAMILIA_CTX% -t %FAMILIA_THREADS% -np 1 -ctk %FAMILIA_KV% -ctv %FAMILIA_KV% --api-key-file "%FAMILIA_API_KEY_FILE%" %FAMILIA_EXTRA% >> "%LOG%" 2>&1
exit /b %ERRORLEVEL%

:help
echo start.bat: start one llama-server node on this Windows machine (settings via FAMILIA_* variables above).
echo Usage: set FAMILIA_MODEL=NAME.gguf ^& scripts\windows\start.bat
echo Example: set FAMILIA_MODEL=qwen2.5-0.5b-instruct-q4_0.gguf ^& scripts\windows\start.bat
echo Licenses are reviewed first (python scripts\licenses.py review). Menu: familia.cmd
exit /b 0
