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
.EXAMPLE
  familia.cmd -Search hermes
.EXAMPLE
  familia.cmd -Search hermes -Run 3 -DryRun
.NOTES
  In the menu, at any level: /word searches every group, ?word searches backward,
  n / N go to the next / previous match, and / alone repeats the last search.
#>
param(
  [switch]$List,
  [string]$Run,
  [switch]$DryRun,
  [switch]$Yes,
  [switch]$Pipe,
  [string]$Search,
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
  'Agents (hermes)' = 'run hermes on one model or the whole graph'; 'Test & benchmark' = 'benchmark records'; 'Hosts' = 'start this node, measure, monitor';
  'Advanced: models & graph' = 'model database, launch arguments, graph edits'; 'Advanced: agents' = 'skill folders, escalation';
  'Advanced: hosts & benchmarks' = 'benchmark records, CPU level, uninstall, logon task'; 'Help' = 'quick start, search, the full command list, what the menu leaves out'
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

# ---- search, like / ? n N in less and more ----
$script:LastSearch = ''; $script:SDir = 1; $script:SCur = 0; $script:SK = @()
function UseColor {
  if ($env:FAMILIA_COLOR -eq 'always') { return $true }
  if ($env:FAMILIA_COLOR -eq 'never' -or $env:NO_COLOR) { return $false }
  try { return -not [Console]::IsOutputRedirected } catch { return $false }
}
function FindMatches($t) {
  $n = $t.ToLower(); $out = @()
  foreach ($i in $items) {
    $hay = ($i.Key + ' ' + $i.Group + ' ' + $i.Label + ' ' + (Shown $i.Cmd)).ToLower()
    if ($hay.Contains($n)) { $out += $i }
  }
  return ,$out
}
function WriteHl($s, $t) {  # write $s, matches of $t highlighted when the console supports it
  if (-not $t -or -not (UseColor)) { Write-Host $s -NoNewline; return }
  $low = $s.ToLower(); $n = $t.ToLower(); $p = 0
  while ($true) {
    $k = $low.IndexOf($n, $p)
    if ($k -lt 0) { break }
    Write-Host $s.Substring($p, $k - $p) -NoNewline
    Write-Host $s.Substring($k, $n.Length) -NoNewline -ForegroundColor Black -BackgroundColor Yellow
    $p = $k + $n.Length
  }
  Write-Host $s.Substring($p) -NoNewline
}
function ShowMatch($num, $i, $t, $mark) {
  $note = ''; if (-not (NeedOk $i.Need)) { $note = ' (not available yet)' }
  if ($i.Gate -eq 'lic') { $note += ' (asks you to accept licenses first)' }
  Write-Host ('{0}{1,2}) ' -f $mark, $num) -NoNewline; WriteHl $i.Group $t; Write-Host ' > ' -NoNewline; WriteHl $i.Label $t; Write-Host $note
  Write-Host '       key: ' -NoNewline; WriteHl $i.Key $t; Write-Host '   runs: ' -NoNewline; WriteHl (Shown $i.Cmd) $t; Write-Host ''
}
function NoMatch($t) { Write-Host "No item matches '$t'. Try a shorter word, or a word from a command (e.g. /hermes, /dry-run)." }
function PrintMatches($t) {
  $m = FindMatches $t
  if ($m.Count -eq 0) { NoMatch $t; return 1 }
  Write-Host "$($m.Count) item(s) match '$t':"
  for ($k = 0; $k -lt $m.Count; $k++) { ShowMatch ($k + 1) $m[$k] $t '  ' }
  return 0
}
function SearchUi($op, $t) {  # returns 'quit' to leave the menu
  if ($op -eq '/' -or $op -eq '?') {
    if (-not $t) { $t = $script:LastSearch }
    if (-not $t) { Write-Host 'No previous search. Type / and a word, e.g. /model'; return '' }
    $script:LastSearch = $t; if ($op -eq '/') { $script:SDir = 1 } else { $script:SDir = -1 }
    $script:SK = FindMatches $t
    if ($script:SK.Count -eq 0) { NoMatch $t; return '' }
    if ($script:SDir -eq 1) { $script:SCur = 0 } else { $script:SCur = $script:SK.Count - 1 }
    Write-Host ''; Write-Host "Search: '$t' ($($script:SK.Count) match(es) in every group; > marks the current one)"
    for ($k = 0; $k -lt $script:SK.Count; $k++) { $mk = '  '; if ($k -eq $script:SCur) { $mk = '> ' }; ShowMatch ($k + 1) $script:SK[$k] $t $mk }
  } else {
    $t = $script:LastSearch
    if (-not $t) { Write-Host 'No previous search. Type / and a word, e.g. /model'; return '' }
    if ($script:SK.Count -eq 0) { $script:SK = FindMatches $t }
    if ($script:SK.Count -eq 0) { NoMatch $t; return '' }
    $c = $script:SK.Count; $d = $script:SDir; if ($op -ceq 'N') { $d = -$d }
    $script:SCur = ($script:SCur + $d + $c) % $c
    Write-Host "match $($script:SCur + 1) of $c for '$t':"
    ShowMatch ($script:SCur + 1) $script:SK[$script:SCur] $t '> '
  }
  while ($true) {
    $c = Read-Host "Choose 1-$($script:SK.Count) to run, n/N next/previous match, /word to search again, b back"
    if ($c -eq $null -or $c -eq '' -or $c -eq 'b') { return '' }
    if ($c -eq 'q') { return 'quit' }
    if ($c -ceq 'n' -or $c -ceq 'N') { return (SearchUi $c '') }
    if ($c.StartsWith('/') -or $c.StartsWith('?')) { return (SearchUi $c.Substring(0, 1) $c.Substring(1)) }
    if (-not ($c -match '^\d+$') -or [int]$c -lt 1 -or [int]$c -gt $script:SK.Count) { Write-Host "'$c' isn't one of the choices. Type a number from 1 to $($script:SK.Count), n, N, /word or b."; continue }
    $script:SCur = [int]$c - 1
    $rc = RunItem $script:SK[$script:SCur].Key @() $true
    if ($rc) { Write-Host "(that step exited with status $rc)" }
    return ''
  }
}
function SearchKey($c) {  # '/x' '?x' 'n' 'N' at any menu prompt: 'quit', 'done', or 'no'
  if ($c.StartsWith('/') -or $c.StartsWith('?')) { $r = SearchUi $c.Substring(0, 1) $c.Substring(1) }
  elseif ($c -ceq 'n' -or $c -ceq 'N') { $r = SearchUi $c '' }
  else { return 'no' }
  if ($r -eq 'quit') { return 'quit' }
  return 'done'
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
if ($Search -and $Run) {  # -Search TEXT -Run N: N is a match number
  $m = FindMatches $Search
  if ($m.Count -eq 0) { NoMatch $Search; exit 1 }
  if ($Run -match '^\d+$') {
    if ([int]$Run -lt 1 -or [int]$Run -gt $m.Count) { Write-Host "familia-menu: -Run ${Run}: there are $($m.Count) match(es) for '$Search'"; exit 2 }
    $Run = $m[[int]$Run - 1].Key
  }
}
if ($Run) { exit (RunItem $Run $RunArgs $false) }
if ($Search) {
  $rc = PrintMatches $Search
  if ($rc -eq 0) { Write-Host "Run one with: familia.cmd -Search `"$Search`" -Run N [ARG...]" }
  exit $rc
}
if ((InputRedirected) -and -not $Pipe) {
  ListItems
  Write-Host 'familia-menu: no console input, so no interactive menu. Run an item with -Run KEY, or pipe choices with -Pipe.'
  exit 2
}
while ($true) {
  Write-Host ''; Write-Host 'familia: what do you want to do?'
  for ($n = 0; $n -lt $groups.Count; $n++) { Write-Host ('  {0}) {1,-36} {2}' -f ($n + 1), $groups[$n], $groupDesc[$groups[$n]]) }
  Write-Host '  q) Quit      /word search every group (n/N next/previous match)'
  $c = Read-Host "Choose 1-$($groups.Count), /search or q"
  if ($c -eq $null -or $c -eq 'q') { exit 0 }
  $sr = SearchKey $c; if ($sr -eq 'quit') { exit 0 }; if ($sr -eq 'done') { continue }
  if (-not ($c -match '^\d+$') -or [int]$c -lt 1 -or [int]$c -gt $groups.Count) { Write-Host "'$c' isn't one of the choices. Type a number, /word to search, or q."; continue }
  $g = $groups[[int]$c - 1]
  while ($true) {
    $gi = @(); foreach ($i in $items) { if ($i.Group -eq $g) { $gi += $i } }
    Write-Host ''; Write-Host "${g}: $($groupDesc[$g])"
    for ($n = 0; $n -lt $gi.Count; $n++) {
      $note = ''; if (-not (NeedOk $gi[$n].Need)) { $note = ' (not available yet)' }
      Write-Host ('  {0}) {1}{2}' -f ($n + 1), $gi[$n].Label, $note)
      Write-Host ('       runs: {0}' -f (Shown $gi[$n].Cmd))
    }
    Write-Host '  b) Back      /word search every group (n/N next/previous match)'
    $c = Read-Host "Choose 1-$($gi.Count), /search or b"
    if ($c -eq $null -or $c -eq 'b' -or $c -eq '') { break }
    if ($c -eq 'q') { exit 0 }
    $sr = SearchKey $c; if ($sr -eq 'quit') { exit 0 }; if ($sr -eq 'done') { continue }
    if (-not ($c -match '^\d+$') -or [int]$c -lt 1 -or [int]$c -gt $gi.Count) { Write-Host "'$c' isn't one of the choices. Type a number, /word to search, or b."; continue }
    $rc = RunItem $gi[[int]$c - 1].Key @() $true
    if ($rc) { Write-Host "(that step exited with status $rc)" }
  }
}
