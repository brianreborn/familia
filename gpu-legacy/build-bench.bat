@echo off
set "PATH=E:\temp\tools\mingw64\bin;%PATH%"
cd /d "%~dp0"
gcc -O2 -fopenmp -o out\bench_matvec.exe bench_matvec.c sm11_shim.c -lm || exit /b 1
echo built out\bench_matvec.exe
