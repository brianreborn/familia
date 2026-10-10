@echo off
setlocal
REM Build run_sm11.exe: CUDA 6.5 sm_11 shim (nvcc) + llama2.c runner (VS2013 cl, plain C). Win32 like green-roomz sm11-monitor.
set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio 12.0\VC\vcvarsall.bat"
set "CUDA_HOME=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v6.5"
call "%VCVARS%" x86 || exit /b 1
cd /d "%~dp0"
if not exist out mkdir out
"%CUDA_HOME%\bin\nvcc.exe" -O2 -m32 -arch=sm_11 -c sm11_shim.cu -o out\sm11_shim.obj || exit /b 1
cl /nologo /O2 /D_CRT_SECURE_NO_WARNINGS /TC /c run.c /Foout\run.obj || exit /b 1
cl /nologo /O2 /D_CRT_SECURE_NO_WARNINGS /TC /c win.c /Foout\win.obj || exit /b 1
link /nologo out\run.obj out\win.obj out\sm11_shim.obj /LIBPATH:"%CUDA_HOME%\lib\Win32" cudart_static.lib /OUT:out\run_sm11.exe || exit /b 1
echo built out\run_sm11.exe
