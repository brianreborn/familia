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

if not defined FAMILIA_MODEL (
  echo familia: set FAMILIA_MODEL to a GGUF in "%FAMILIA_MODELS%" 1>&2
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
set "BIN=%FAMILIA_RUNTIME%\llama-server.exe"
if not exist "%BIN%" (
  echo familia: llama-server.exe not found in "%FAMILIA_RUNTIME%" ^(unzip llama-*-bin-win-cpu-x64.zip there^) 1>&2
  exit /b 2
)

if not exist "%FAMILIA_MODELS%\..\logs" mkdir "%FAMILIA_MODELS%\..\logs" >nul 2>&1
set "LOG=%FAMILIA_MODELS%\..\logs\llama-server-%FAMILIA_PORT%.log"
echo familia: %BIN% -m "%MODEL%" on %FAMILIA_BIND%:%FAMILIA_PORT% (log %LOG%)
"%BIN%" -m "%MODEL%" --host %FAMILIA_BIND% --port %FAMILIA_PORT% -c %FAMILIA_CTX% -t %FAMILIA_THREADS% -np 1 -ctk %FAMILIA_KV% -ctv %FAMILIA_KV% %FAMILIA_EXTRA% >> "%LOG%" 2>&1
exit /b %ERRORLEVEL%
