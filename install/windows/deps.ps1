#Requires -Version 5.1
<#
.SYNOPSIS
  Check (and optionally hint-install) tools familia / code-bootstraps need on Windows.
.DESCRIPTION
  Windows has no apt-like set of many small packages for this project. We check for
  git, python, cmake (and optionally a C++ toolchain), then point at winget / choco
  or "build from source" via the pinned code-bootstraps-llama.cpp scripts.
  Safe-mode build AI home: code-bootstraps-llama.cpp (see docs/safe-mode-bootstrap.md).
.PARAMETER Install
  Attempt winget installs for missing tools (git, Python.Python.3.12, Kitware.CMake).
.PARAMETER Yes
  Non-interactive (passed through; still uses winget --accept-package-agreements).
.PARAMETER DryRun
  Print what would be run; change nothing.
.PARAMETER Profile
  base (default) or build (also want Visual Studio Build Tools / cmake).
#>
[CmdletBinding()]
param(
  [switch]$Install,
  [Alias('y')][switch]$Yes,
  [Alias('n')][switch]$DryRun,
  [ValidateSet('base','build')][string]$Profile = 'base'
)

$ErrorActionPreference = 'Continue'
function Say([string]$m) { Write-Host "familia-deps: $m" }

function Have-Cmd([string]$name) {
  return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

$present = @()
$missing = @()
$hints = @()

if (Have-Cmd 'git') { $present += 'git' } else {
  $missing += 'git'
  $hints += 'winget install --id Git.Git -e'
}
$py = $null
foreach ($c in @('python3','python','py')) {
  if (Have-Cmd $c) {
    try {
      $v = & $c --version 2>$null
      if ($v -match 'Python') { $py = $c; break }
    } catch {}
  }
}
if ($py) { $present += "python($py)" } else {
  $missing += 'python'
  $hints += 'winget install --id Python.Python.3.12 -e'
}
# pytest via python -m
$havePytest = $false
if ($py) {
  try {
    & $py -m pytest --version 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $havePytest = $true }
  } catch {}
}
if ($havePytest) { $present += 'pytest' } else {
  $missing += 'pytest'
  $hints += if ($py) { "$py -m pip install pytest pyyaml" } else { 'pip install pytest pyyaml (after Python)' }
}
$haveYaml = $false
if ($py) {
  try {
    & $py -c 'import yaml' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $haveYaml = $true }
  } catch {}
}
if ($haveYaml) { $present += 'pyyaml' } else {
  $missing += 'pyyaml'
  if ($py) { $hints += "$py -m pip install pyyaml" }
}
if (Have-Cmd 'cmake') { $present += 'cmake' }
elseif ($Profile -eq 'build') {
  $missing += 'cmake'
  $hints += 'winget install --id Kitware.CMake -e'
}
if ($Profile -eq 'build') {
  $cxx = (Have-Cmd 'cl') -or (Test-Path "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe")
  if ($cxx) { $present += 'msvc-or-vswhere' }
  else {
    $missing += 'vs-build-tools'
    $hints += 'winget install --id Microsoft.VisualStudio.2022.BuildTools -e  (C++ workload), or build via code-bootstraps scripts\build-windows.ps1 after VS is present'
  }
}

Say "platform=Windows profile=$Profile"
Say ("present: " + ($(if ($present) { $present -join ' ' } else { '(none)' })))
Say ("missing: " + ($(if ($missing) { $missing -join ' ' } else { '(none)' })))
Say "Windows has comparatively few apt-like packages; prefer official binaries (winget/choco) or build from source."
Say "home of the safe-mode *build* AI: pinned code-bootstraps-llama.cpp (scripts\build-windows.ps1 / start.bat)"

if (-not $missing) {
  Say 'all required tools look present'
  exit 0
}

Say 'suggested:'
foreach ($h in $hints) { Say "  $h" }

if (-not $Install) {
  Say 're-run with -Install to attempt winget/pip for missing tools (-Yes for non-interactive)'
  exit 1
}
if ($DryRun) {
  Say '[dry-run] would run the suggested commands above'
  exit 0
}
if (-not $Yes) {
  $ans = Read-Host 'familia-deps: run suggested installs now? [y/N]'
  if ($ans -notmatch '^(y|yes)$') { Say 'aborted'; exit 1 }
}

$winget = Get-Command winget -ErrorAction SilentlyContinue
foreach ($m in $missing) {
  switch ($m) {
    'git' {
      if ($winget) { winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements }
      else { Say 'winget not found; install Git from https://git-scm.com/download/win' }
    }
    'python' {
      if ($winget) { winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements }
      else { Say 'winget not found; install Python from https://www.python.org/downloads/' }
    }
    'cmake' {
      if ($winget) { winget install --id Kitware.CMake -e --accept-package-agreements --accept-source-agreements }
      else { Say 'winget not found; install CMake from https://cmake.org/download/' }
    }
    'pytest' {
      $p = if ($py) { $py } else { 'python' }
      & $p -m pip install pytest 2>$null
    }
    'pyyaml' {
      $p = if ($py) { $py } else { 'python' }
      & $p -m pip install pyyaml 2>$null
    }
    'vs-build-tools' {
      Say 'Visual Studio Build Tools: install the "Desktop development with C++" workload, then rebuild via code-bootstraps.'
      if ($winget) {
        winget install --id Microsoft.VisualStudio.2022.BuildTools -e --accept-package-agreements --accept-source-agreements
      }
    }
  }
}
Say 'done (re-open the shell so PATH picks up new tools)'
