<#
.SYNOPSIS
  Six equal home items for Windows (mirrors scripts/familia_home.sh).
  gum.exe when it is on PATH. If gum cannot be installed, the legacy menu runs.
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\familia-home.ps1
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\familia-home.ps1 -ListGoals
#>
param(
  [switch]$ListGoals
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root

function Find-Python {
  foreach ($name in @('python', 'python3', 'py')) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
  }
  return $null
}
$script:PyExe = Find-Python

function Show-Goals {
  if (-not $script:PyExe) {
    Write-Host 'familia-home: python was not found'
    exit 1
  }
  & $script:PyExe (Join-Path $root 'scripts\home_catalog.py') --list-home
  exit $LASTEXITCODE
}

if ($ListGoals -or $env:FAMILIA_NO_TTY -eq '1' -or -not [Environment]::UserInteractive) {
  Show-Goals
}

function Enter-Legacy([string]$why) {
  Write-Host "familia-home: $why"
  Write-Host 'familia-home: falling back to the legacy menu. Type q to quit.'
  $menu = Join-Path $root 'scripts\windows\familia-menu.ps1'
  & powershell -NoProfile -ExecutionPolicy Bypass -File $menu
  exit $LASTEXITCODE
}

if (-not $script:PyExe) { Enter-Legacy 'python was not found' }

function Test-Gum {
  return [bool](Get-Command gum -ErrorAction SilentlyContinue)
}
if (-not (Test-Gum)) {
  if ($env:FAMILIA_SKIP_GUM_INSTALL -ne '1') {
    $inst = Join-Path $root 'scripts\windows\install-gum.ps1'
    if (Test-Path $inst) {
      try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $inst -Yes
      } catch {
        Write-Host 'familia-home: gum install did not finish'
      }
    }
  }
}
if (-not (Test-Gum)) {
  Enter-Legacy 'gum is not available and could not be installed'
}

function Show-Banner {
  Write-Host '  +------------------------------------------------------------------+'
  Write-Host '  | familia   six equal items   Quit is the only exit               |'
  Write-Host '  +------------------------------------------------------------------+'
}

function Pick-One([string]$header, [string[]]$options) {
  $sel = & gum choose --header $header --height 16 @options
  if ($LASTEXITCODE -ne 0 -or -not $sel) { return $null }
  return [string]$sel
}

function Area-Of([string]$title) {
  switch ($title) {
    'Models' { 'models' }
    'Harnesses' { 'harnesses' }
    'Agents' { 'agents' }
    'MCP servers' { 'mcp' }
    'Tool sets' { 'tools' }
    'App store' { 'apps' }
    default { '' }
  }
}

function Invoke-Verb([string]$area, [string]$verb) {
  $apply = $false
  if ($verb -eq 'install' -or $verb -eq 'start' -or $verb -eq 'stop') {
    try {
      $ans = Read-Host "Run $area $verb now (--apply)? [y/N]"
    } catch {
      Write-Host 'familia-home: not confirmed. Staying in the menu.'
      return
    }
    if ($ans -eq 'y' -or $ans -eq 'Y' -or $ans -eq 'yes' -or $ans -eq 'YES') {
      $apply = $true
    } else {
      Write-Host 'familia-home: not confirmed. Staying in the menu.'
      return
    }
  }
  if ($apply) {
    & $script:PyExe (Join-Path $root 'scripts\home_catalog.py') $area $verb '--apply'
  } else {
    & $script:PyExe (Join-Path $root 'scripts\home_catalog.py') $area $verb
  }
  if ($LASTEXITCODE -ne 0) {
    Write-Host "familia-home: $area $verb exited $LASTEXITCODE. Staying in the menu."
  }
}

function Enter-Area([string]$area, [string]$title) {
  while ($true) {
    $sel = Pick-One "$title : install, list, start, stop, status. Quit leaves." @(
      'install', 'list', 'start', 'stop', 'status', 'Back', 'Quit')
    if (-not $sel) {
      Write-Host "familia-home: staying in $title. Choose Back or Quit."
      continue
    }
    switch ($sel) {
      'Quit' { exit 0 }
      'Back' { return }
      { $_ -in @('install', 'list', 'start', 'stop', 'status') } { Invoke-Verb $area $sel }
      default { Write-Host "familia-home: unknown choice $sel. Staying in the menu." }
    }
  }
}

$titles = @('Models', 'Harnesses', 'Agents', 'MCP servers', 'Tool sets', 'App store')
while ($true) {
  Show-Banner
  $sel = Pick-One 'What do you want to do? Quit is the only exit.' @(
    $titles + @('Legacy menu', 'Quit'))
  if (-not $sel) {
    Write-Host 'familia-home: staying in the menu. Choose Quit to leave.'
    continue
  }
  switch ($sel) {
    'Quit' { exit 0 }
    'Legacy menu' {
      $menu = Join-Path $root 'scripts\windows\familia-menu.ps1'
      & powershell -NoProfile -ExecutionPolicy Bypass -File $menu
      if ($LASTEXITCODE -ne 0) {
        Write-Host "familia-home: legacy menu exited $LASTEXITCODE. Staying in the menu."
      }
    }
    default {
      $area = Area-Of $sel
      if (-not $area) {
        Write-Host "familia-home: unknown choice $sel. Staying in the menu."
        continue
      }
      Enter-Area $area $sel
    }
  }
}
