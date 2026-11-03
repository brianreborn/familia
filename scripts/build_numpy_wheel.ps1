<#
.SYNOPSIS
  Build a numpy 2.4+ wheel that runs on pre-x86-64-v2 CPUs (e.g. Athlon II X2) on Windows.
.DESCRIPTION
  NumPy >= 2.4 wheels need X86_V2 and crash with 0xc000001d on older CPUs. This builds from the
  sdist with -Dcpu-baseline=none (runtime dispatch still picks SSE4/AVX where present) using
  MSYS2 ucrt64 gcc, into a throwaway venv, so the user's own numpy is never touched.
  No BLAS (-Dblas=none): linalg uses numpy's bundled lapack_lite. -mlong-double-64 matches MSVC Python.
  Prereq: MSYS2 at C:\msys64 with: pacman -S mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-pkgconf
  Long: run it detached (Start-Process) and watch $Work\build.log.
.EXAMPLE
  powershell -File scripts\build_numpy_wheel.ps1 -Version 2.5.3 -Work E:\temp\numpy-build
#>
param([string]$Version = '2.5.3', [string]$Work = "$env:TEMP\numpy-build", [string]$Msys = 'C:\msys64', [string]$Python = 'python')
$ErrorActionPreference = 'Stop'
if (-not (Test-Path "$Msys\ucrt64\bin\gcc.exe")) { throw "no $Msys\ucrt64\bin\gcc.exe; install MSYS2 and: pacman -S mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-pkgconf" }
New-Item -ItemType Directory -Force $Work, "$Work\x", "$Work\wheels" | Out-Null
Set-Location $Work
if (-not (Test-Path venv\Scripts\python.exe)) { & $Python -m venv venv }
$vp = "$Work\venv\Scripts\python.exe"
& $vp -m pip install -q -U pip meson-python meson ninja cython pyproject-metadata packaging
$sd = "$Work\x\numpy-$Version"
if (-not (Test-Path $sd)) {
  & $vp -m pip download --no-deps --no-binary :all: -d src "numpy==$Version"
  tar -xzf "src\numpy-$Version.tar.gz" -C x
}
$env:Path = "$Msys\ucrt64\bin;$Work\venv\Scripts;" + $env:Path
$env:CC = 'gcc'; $env:CXX = 'g++'; $env:CFLAGS = '-mlong-double-64'; $env:CXXFLAGS = '-mlong-double-64'
cmd /c "`"$vp`" -m pip wheel --no-deps --no-build-isolation -w wheels `"$sd`" -v -Csetup-args=-Dcpu-baseline=none -Csetup-args=-Dcpu-dispatch=max -Csetup-args=-Dallow-noblas=true -Csetup-args=-Dblas=none -Csetup-args=-Dlapack=none > build.log 2>&1"
"EXIT $LASTEXITCODE $(Get-Date)" | Out-File build.log -Append -Encoding ascii
if ($LASTEXITCODE) { throw "build failed, see $Work\build.log" }
$whl = Get-ChildItem wheels -Filter "numpy-$Version-*.whl" | Select-Object -First 1
& $vp -m pip install -q --no-deps --force-reinstall $whl.FullName
& $vp -W ignore -c "import numpy as np; np.show_runtime(); a=np.random.rand(200,200); print('ok', np.__version__, float((a@a).sum()))"
if ($LASTEXITCODE) { throw 'import/smoke test failed' }
"wheel: $($whl.FullName)"
