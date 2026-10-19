<#
.SYNOPSIS
  familia menu for Windows. Same items as ./familia-menu.sh (scripts\menu-items.txt).
.DESCRIPTION
  Every item shows the command it runs. Items that only exist on Linux/Android are
  hidden here. Items marked "asks you to accept licenses" run scripts\licenses.py gate
  first. With no console input (redirected) and no -List/-Run/-Pipe it prints the
  items and exits 2 instead of waiting.
.EXAMPLE
  familia.cmd
.EXAMPLE
  familia.cmd -List
.EXAMPLE
  familia.cmd -Run skills.list
.EXAMPLE
  familia.cmd -Run models.explain coder -DryRun
#>
param(
  [switch]$List,
  [string]$Run,
  [switch]$DryRun,
  [switch]$Yes,
  [switch]$Pipe,
  [Parameter(ValueFromRemainingArguments = $true)] [string[]]$RunArgs
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $root
if ($Yes) { $env:FAMILIA_ACCEPT_LICENSES = 'yes' }
if ($Pipe) { $env:FAMILIA_MENU_PIPE = '1' }
$itemsFile = Join-Path $root 'scripts\menu-items.txt'
if (-not (Test-Path $itemsFile)) { Write-Host "familia-menu: $itemsFile is missing; restore it with: git checkout scripts/menu-items.txt"; exit 1 }

$items = @()
foreach ($line in (Get-Content $itemsFile)) {
  if ($line -match '^\s*#' -or $line -match '^\s*$') { continue }
  $f = $line.Split('|')
  if ($f.Count -lt 7 -or -not $f[6]) { continue }   # no Windows command
  $items += New-Object PSObject -Property @{ Key = $f[0]; Group = $f[1]; Label = $f[2]; Gate = $f[4]; Need = $f[5]; Cmd = $f[6] }
}
$groupDesc = @{
  'Set up' = 'licenses, settings, install'; 'Skills' = 'pick the skills your agents use (green-zkillz)';
  'Models' = 'add models, check the graph, see launch parameters'; 'Self-improving harness (Harness2)' = 'opt-in; review every change';
  'Test & benchmark' = 'benchmark records'; 'Hosts' = 'start this node, per-host graph'; 'Help' = 'quick start and the full command list'
}
$groups = @(); foreach ($i in $items) { if (-not ($groups -contains $i.Group)) { $groups += $i.Group } }

function NeedOk($spec) {
  if (-not $spec) { return $true }
  if ($spec.StartsWith('file:')) { return (Test-Path ($spec.Substring(5) -replace '/', '\')) }
  if ($spec.StartsWith('grep:')) {
    $rest = $spec.Substring(5); $k = $rest.IndexOf(':'); $p = $rest.Substring(0, $k) -replace '/', '\'; $t = $rest.Substring($k + 1)
    if (-not (Test-Path $p)) { return $false }
    return [bool](Select-String -Path $p -SimpleMatch -Pattern $t -Quiet)
  }
  return $false
}
function Shown($c) { return ($c -replace '\{([A-Z]+):[^}]*\}', '<$1>') }
function InputRedirected { try { return [Console]::IsInputRedirected } catch { return $false } }

function Fill($cmd, $vals, $interactive) {
  $n = 0
  while ($cmd -match '\{([A-Z]+):([^}]*)\}') {
    $whole = $matches[0]; $name = $matches[1]; $prompt = $matches[2]; $def = ''
    if ($prompt -match '\[([^\]]*)\]') { $def = $matches[1] }
    if ($vals -and $n -lt $vals.Count) { $v = $vals[$n]; $n++ }
    elseif ($interactive) { $v = Read-Host "  $prompt" }
    else { Write-Host "familia-menu: item needs $name ($prompt). Pass it after the key: -Run KEY VALUE"; return $null }
    if (-not $v) { $v = $def }
    if (-not $v) { Write-Host "familia-menu: $name is required ($prompt)"; return $null }
    $cmd = $cmd.Replace($whole, '"' + $v + '"')
  }
  return $cmd
}

function RunItem($key, $vals, $interactive) {
  $it = $null; foreach ($i in $items) { if ($i.Key -eq $key) { $it = $i } }
  if (-not $it) { Write-Host "familia-menu: no Windows item '$key'. See: familia.cmd -List"; return 2 }
  if (-not (NeedOk $it.Need)) { Write-Host "familia-menu: '$($it.Label)' is not available yet (needs $($it.Need.Substring(5)))."; return 1 }
  $cmd = Fill $it.Cmd $vals $interactive
  if (-not $cmd) { return 2 }
  if ($DryRun) {
    if ($it.Gate -eq 'lic') { Write-Host '[dry-run] would first run: python scripts\licenses.py gate' }
    Write-Host "[dry-run] $cmd"; return 0
  }
  if ($it.Gate -eq 'lic') {
    & python scripts\licenses.py gate | Out-Host
    if ($LASTEXITCODE) { Write-Host 'familia-menu: stopped: licenses not accepted yet. Review them with: python scripts\licenses.py review'; return $LASTEXITCODE }
  }
  Write-Host "Running: $cmd"
  & cmd.exe /c $cmd | Out-Host
  return $LASTEXITCODE
}

function ListItems {
  Write-Host 'familia menu items (Windows). Run one with: familia.cmd -Run KEY [ARG...]'
  foreach ($g in $groups) {
    Write-Host ''; Write-Host "${g}: $($groupDesc[$g])"
    foreach ($i in $items) {
      if ($i.Group -ne $g) { continue }
      $note = ''; if (-not (NeedOk $i.Need)) { $note = '  (not available yet)' }
      if ($i.Gate -eq 'lic') { $note += '  (asks you to accept licenses first)' }
      Write-Host ('  {0,-22} {1}{2}' -f $i.Key, $i.Label, $note)
      Write-Host ('  {0,-22}   runs: {1}' -f '', (Shown $i.Cmd))
    }
  }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Host 'familia-menu: python was not found. Install Python 3 from python.org (tick "Add to PATH"), then run familia.cmd again.'
  exit 1
}
if ($List) { ListItems; exit 0 }
if ($Run) { exit (RunItem $Run $RunArgs $false) }
if ((InputRedirected) -and -not $Pipe) {
  ListItems
  Write-Host 'familia-menu: no console input, so no interactive menu. Run an item with -Run KEY, or pipe choices with -Pipe.'
  exit 2
}
while ($true) {
  Write-Host ''; Write-Host 'familia: what do you want to do?'
  for ($n = 0; $n -lt $groups.Count; $n++) { Write-Host ('  {0}) {1,-36} {2}' -f ($n + 1), $groups[$n], $groupDesc[$groups[$n]]) }
  Write-Host '  q) Quit'
  $c = Read-Host "Choose 1-$($groups.Count) or q"
  if ($c -eq $null -or $c -eq 'q') { exit 0 }
  if (-not ($c -match '^\d+$') -or [int]$c -lt 1 -or [int]$c -gt $groups.Count) { Write-Host "'$c' isn't one of the choices."; continue }
  $g = $groups[[int]$c - 1]
  while ($true) {
    $gi = @(); foreach ($i in $items) { if ($i.Group -eq $g) { $gi += $i } }
    Write-Host ''; Write-Host "${g}: $($groupDesc[$g])"
    for ($n = 0; $n -lt $gi.Count; $n++) {
      $note = ''; if (-not (NeedOk $gi[$n].Need)) { $note = ' (not available yet)' }
      Write-Host ('  {0}) {1}{2}' -f ($n + 1), $gi[$n].Label, $note)
      Write-Host ('       runs: {0}' -f (Shown $gi[$n].Cmd))
    }
    Write-Host '  b) Back'
    $c = Read-Host "Choose 1-$($gi.Count) or b"
    if ($c -eq $null -or $c -eq 'b' -or $c -eq '') { break }
    if ($c -eq 'q') { exit 0 }
    if (-not ($c -match '^\d+$') -or [int]$c -lt 1 -or [int]$c -gt $gi.Count) { Write-Host "'$c' isn't one of the choices."; continue }
    $rc = RunItem $gi[[int]$c - 1].Key @() $true
    if ($rc) { Write-Host "(that step exited with status $rc)" }
  }
}
