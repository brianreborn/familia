@echo off
REM Build with portable mingw-w64 gcc (E:\temp\tools\mingw64). No CUDA toolkit or MSVC required.
set "PATH=E:\temp\tools\mingw64\bin;%PATH%"
cd /d "%~dp0"
if not exist out mkdir out
gcc -O2 -fopenmp -Wno-incompatible-pointer-types -o out\run_sm11.exe run.c win.c sm11_shim.c -lm || exit /b 1
echo built out\run_sm11.exe
