<#
.SYNOPSIS
  Goal-oriented Set up flows for the familia Windows menu (mirrors scripts/setup_goals.sh).
.DESCRIPTION
  Goals: first-time | sync-pins | remove-path.
  Charm/gum presentation is a later pass — this script is content/structure only.
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\setup-goals.ps1 -Goal first-time -WhatIf
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\setup-goals.ps1 -Goal sync-pins
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('first-time', 'sync-pins', 'remove-path')]
  [string]$Goal,
  [switch]$Yes,
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
if ($DryRun) { $WhatIfPreference = $true }
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root
function Say([string]$m) { Write-Host "familia-setup: $m" }
function ConfirmAsk([string]$q) {
  if ($Yes) { return $true }
  if (-not [Environment]::UserInteractive) { return $false }
  $a = Read-Host "$q [y/N]"
  return ($a -eq 'y' -or $a -eq 'Y' -or $a -eq 'yes' -or $a -eq 'YES')
}
function RunStep([string]$label, [scriptblock]$block) {
  Say "==> $label"
  if ($WhatIfPreference) { Say "[dry-run] $label"; return }
  & $block
}

switch ($Goal) {
  'first-time' {
    Say 'Goal: first-time setup on this machine'
    $deps = Join-Path $root 'install\windows\deps.ps1'
    $install = Join-Path $root 'install\windows\install.ps1'
    $cli = Join-Path $root 'scripts\windows\install-cli.ps1'
    if (Test-Path $deps) {
      RunStep 'Install OS packages this host needs' { & powershell -NoProfile -ExecutionPolicy Bypass -File $deps -Install }
    } else { Say "skip deps: $deps not found" }
    RunStep 'Review licenses' { & python (Join-Path $root 'scripts\licenses.py') review }
    # configure.sh is POSIX-only; Windows uses sync_pins as the closest checkout setup step
    RunStep 'Sync pinned parts (Windows stand-in for configure.sh)' { & python (Join-Path $root 'scripts\sync_pins.py') }
    RunStep 'Install preview (dry-run)' { & powershell -NoProfile -ExecutionPolicy Bypass -File $install -DryRun }
    if ($WhatIfPreference) {
      Say '[dry-run] would ask: Apply install?'
      Say '[dry-run] would offer: Put familia on PATH?'
      Say '[dry-run] next: Hosts → start (hosts.start)'
      break
    }
    if (ConfirmAsk 'Apply install on this host?') {
      RunStep 'Install for real' { & powershell -NoProfile -ExecutionPolicy Bypass -File $install }
    } else { Say 'Skipped install.' }
    RunStep 'PATH preview' { & powershell -NoProfile -ExecutionPolicy Bypass -File $cli -WhatIf }
    if (ConfirmAsk 'Put familia on your PATH?') {
      RunStep 'Install familia CLI shim' { & powershell -NoProfile -ExecutionPolicy Bypass -File $cli }
    } else { Say 'Skipped PATH.' }
    Say ''
    Say 'First-time setup finished.'
    Say 'Next: Hosts → start (hosts.start) or: familia.cmd -Run hosts.start'
  }
  'sync-pins' {
    Say 'Goal: sync pinned parts only'
    if ($WhatIfPreference) {
      Say '[dry-run] would ask: preview or apply?'
      Say '[dry-run] preview: python scripts\sync_pins.py --dry-run'
      Say '[dry-run] apply:   python scripts\sync_pins.py'
      break
    }
    $c = Read-Host 'Sync pins: [p]review (no changes), [a]pply, or [q]uit?'
    switch -Regex ($c) {
      '^[pP]' { RunStep 'Preview pin sync' { & python (Join-Path $root 'scripts\sync_pins.py') --dry-run } }
      '^[aA]' { RunStep 'Apply pin sync' { & python (Join-Path $root 'scripts\sync_pins.py') } }
      default { Say 'Cancelled.' }
    }
  }
  'remove-path' {
    Say 'Goal: remove familia from PATH (danger)'
    $cli = Join-Path $root 'scripts\windows\install-cli.ps1'
    if ($WhatIfPreference) {
      Say '[dry-run] would preview uninstall-cli, then confirm remove'
      break
    }
    RunStep 'Uninstall preview' { & powershell -NoProfile -ExecutionPolicy Bypass -File $cli -Uninstall -WhatIf }
    if (ConfirmAsk 'Remove familia from PATH for real?') {
      RunStep 'Uninstall CLI from PATH' { & powershell -NoProfile -ExecutionPolicy Bypass -File $cli -Uninstall }
    } else { Say 'Cancelled — PATH unchanged.' }
  }
}
