@echo off
set PATH=E:\temp\tools\mingw64\bin;%PATH%
cd /d %~dp0
gcc -O2 -o out\bench_quant.exe bench_quant.c sm11_shim.c -lm || exit /b 1
echo built out\bench_quant.exe
