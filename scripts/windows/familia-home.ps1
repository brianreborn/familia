<#
.SYNOPSIS
  Charm-style goal launcher for Windows (mirrors scripts/familia_home.sh).
  gum.exe on PATH preferred; falls back to Out-Host numbered choose.
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
$goals = @(
  'Talk to the protomodel',
  'Find more models',
  'Search my X / Twitter posts',
  'Install / first-time setup',
  '★ Required checks (must-run)',
  'Legacy menu'
)
if ($ListGoals -or $env:FAMILIA_NO_TTY -eq '1' -or -not [Environment]::UserInteractive) {
  Write-Host 'familia home — goals:'
  for ($i = 0; $i -lt $goals.Count; $i++) { Write-Host ("  {0}) {1}" -f ($i+1), $goals[$i]) }
  Write-Host 'Legacy fallback: familia.cmd -LegacyMenu'
  exit 0
}
function Write-PilotCanopy([string]$title = 'FAMILIA PILOT LINK') {
  Write-Host ''
  Write-Host ('  ╔' + ('═' * 70) + '╗') -ForegroundColor Cyan
  Write-Host ('  ║  ◈ ' + $title.PadRight(64) + '◈  ║') -ForegroundColor Cyan
  Write-Host ('  ║  COCKPIT HUD  ·  FRAME SYNC  ·  ORDNANCE PREFETCH' + (' ' * 18) + '║') -ForegroundColor DarkCyan
  Write-Host ('  ╚' + ('═' * 70) + '╝') -ForegroundColor Cyan
}
function Start-OrdnancePrefetch {
  $pf = Join-Path $root 'scripts\windows\prefetch-first-models.ps1'
  Write-Host '  [PREFETCHING ORDNANCE] first-try models in background…' -ForegroundColor Yellow
  if (Test-Path $pf) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $pf -Background | Out-Null
  }
}

$gum = Get-Command gum -ErrorAction SilentlyContinue
if (-not $gum) {
  Write-Host 'familia-home: gum (Charm) is required for the new front door.' -ForegroundColor Yellow
  Write-Host 'Install (user-local):  powershell -File scripts\windows\install-gum.ps1 -Yes'
  Write-Host '     or re-run:        install\windows\install.ps1 -Yes'
  Write-Host 'Legacy menu (no gum):  familia.cmd -LegacyMenu'
  exit 2
}
Write-PilotCanopy 'FAMILIA PILOT LINK'
$choice = $goals | & gum choose --header 'What do you want to do?' --height 10
if (-not $choice) { Write-Host 'familia-home: cancelled'; exit 0 }
switch ($choice) {
  'Talk to the protomodel' {
    Start-OrdnancePrefetch
    $bash = Get-Command bash -ErrorAction SilentlyContinue
    if ($bash) {
      & bash "$root\scripts\proto_chat.sh"
    } else {
      Write-Host 'Start bootstrap: .\start.bat  then open http://127.0.0.1:9931/?model=chat'
      Write-Host 'Or install Git Bash / WSL and re-run Talk to the protomodel.'
    }
  }
  'Find more models' {
    & bash "$root\scripts\find_models.sh"
  }
  'Search my X / Twitter posts' {
    & bash "$root\scripts\search_x.sh"
  }
  'Install / first-time setup' {
    Start-OrdnancePrefetch
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\windows\setup-goals.ps1" -Goal first-time
  }
  '★ Required checks (must-run)' {
    & bash "$root\scripts\required_checks.sh"
  }
  'Legacy menu' {
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\windows\familia-menu.ps1"
  }
}
