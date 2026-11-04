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
  [switch]$Cli,   # familia.cmd COMMAND ...: the words come in $env:FAMILIA_CLI_ARGS (see familia.cmd)
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
  'Set up' = 'first-time, update, licenses, settings'; 'Skills' = 'pick the skills your agents use (green-zkillz)';
  'Models' = 'add models, check the graph, see launch parameters'; 'Self-improving harness (Harness2)' = 'opt-in; review every change';
  'Agents (hermes)' = 'run hermes on one model or the whole graph'; 'Test & benchmark' = 'benchmark records'; 'Hosts' = 'start this node, measure, monitor';
  'Advanced: models & graph' = 'model database, launch arguments, graph edits'; 'Advanced: agents' = 'skill folders, escalation';
  'Advanced: hosts & benchmarks' = 'low-level setup, benchmarks, CPU level, uninstall, logon task'; 'Reach tools (Agent-Reach)' = 'opt agents into Agent-Reach web tools'; 'Help' = 'quick start, search, the full command list, what the menu leaves out'
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

function CanPrompt { return (-not (InputRedirected)) -and $env:FAMILIA_NO_TTY -ne '1' }
function ShortHostname {
  $name = $env:COMPUTERNAME
  if (-not $name) { $name = [System.Net.Dns]::GetHostName() }
  return (($name -split '\.')[0]).ToLowerInvariant()
}
function PinnedOrShortHostname {
  $pinPy = Join-Path $root "scripts\hostname_pin.py"
  if (Test-Path $pinPy) {
    $p = & python $pinPy resolve 2>$null
    if ($LASTEXITCODE -eq 0 -and $p) { return ($p | Select-Object -First 1).Trim() }
  }
  return ShortHostname
}
function Quote($v) { if ($v -eq '' -or $v -match '[\s&|<>^"]') { return '"' + $v + '"' }; return $v }
$script:Me = 'familia-menu'; $script:CliHint = ''
# Fill CMD VALS: {NAME:prompt [default]} from VALS (as the --flag written before it, else in order),
# else a prompt (menu, or a console when there is no default), else the default. The rest is appended.
function Fill($cmd, $vals, $interactive) {
  $rest = New-Object System.Collections.ArrayList
  if ($vals) { foreach ($v in $vals) { [void]$rest.Add([string]$v) } }
  $ph = @([regex]::Matches($cmd, '\{([A-Z]+):([^}]*)\}'))
  $got = @{}
  foreach ($m in $ph) {  # --flag VALUE / --flag=VALUE given by the user
    if (-not ($cmd.Substring(0, $m.Index) -match '(^|\s)(-[-A-Za-z0-9]+)\s+$')) { continue }
    $flag = $matches[2]
    for ($i = 0; $i -lt $rest.Count; $i++) {
      if ($rest[$i] -eq $flag -and $i + 1 -lt $rest.Count) { $got[$m.Index] = $rest[$i + 1]; $rest.RemoveRange($i, 2); break }
      if ($rest[$i].StartsWith($flag + '=')) { $got[$m.Index] = $rest[$i].Substring($flag.Length + 1); $rest.RemoveAt($i); break }
    }
  }
  $hint = $script:CliHint; if (-not $hint) { $hint = 'familia.cmd -Run KEY' }
  $out = ''; $pos = 0
  foreach ($m in $ph) {
    $name = $m.Groups[1].Value; $prompt = $m.Groups[2].Value; $def = ''
    if ($prompt -match '\[([^\]]*)\]') { $def = $matches[1] }
    if ($def -eq 'hostname') {
      $def = PinnedOrShortHostname
      if ($def) { $prompt = $prompt -replace '\[hostname\]', "[$def]" }
      else { $prompt = $prompt -replace ' \[hostname\]', '' }
    }
    if ($got.ContainsKey($m.Index)) { $v = $got[$m.Index] }
    elseif ($rest.Count -gt 0 -and -not $rest[0].StartsWith('-')) { $v = $rest[0]; $rest.RemoveAt(0) }
    elseif ($interactive -or (-not $def -and (CanPrompt))) { $v = Read-Host "  $prompt" }
    elseif (-not $def) { Write-Host "$($script:Me): item needs $name ($prompt). Give it as a value: $hint VALUE"; return $null }
    else { $v = '' }
    if (-not $v) { $v = $def }
    if (-not $v) { Write-Host "$($script:Me): $name is required ($prompt)"; return $null }
    $out += $cmd.Substring($pos, $m.Index - $pos) + '"' + $v + '"'; $pos = $m.Index + $m.Length
  }
  $out += $cmd.Substring($pos)
  foreach ($v in $rest) { $out += ' ' + (Quote $v) }
  return $out
}

function RunItem($key, $vals, $interactive) {
  $it = $null; foreach ($i in $items) { if ($i.Key -eq $key) { $it = $i } }
  if (-not $it) { Write-Host "$($script:Me): no Windows item '$key'. See: familia.cmd -List"; return 2 }
  if (-not (NeedOk $it.Need)) { Write-Host "$($script:Me): '$($it.Label)' is not available yet (needs $($it.Need.Substring(5)))."; return 1 }
  $cmd = Fill $it.Cmd $vals $interactive
  if (-not $cmd) { return 2 }
  return (RunCmd $it.Gate $cmd)
}
function RunCmd($gate, $cmd) {  # the license gate when asked for, then the command (or print it with -DryRun)
  if ($DryRun) {
    if ($gate -eq 'lic') { Write-Host '[dry-run] would first run: python scripts\licenses.py gate' }
    Write-Host "[dry-run] $cmd"; return 0
  }
  if ($gate -eq 'lic') {
    & python scripts/licenses.py gate | Out-Host
    if ($LASTEXITCODE) { Write-Host "$($script:Me): stopped: licenses not accepted yet. Review them with: python scripts\licenses.py review"; return $LASTEXITCODE }
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

function ShowWorkflowPaths {
  Write-Host 'GOALS (pick one; Set up group has the same first-time path as a single choice):'
  Write-Host '  New checkout: setup.first-time  (deps -> licenses -> configure -> install -> PATH)'
  Write-Host '                then hosts.start'
  Write-Host '  Existing graph node: models.check -> hosts.serve <NODE>'
  Write-Host '  Add a model: models.fetch-preview -> models.fetch -> add its node to graph.yaml ->'
  Write-Host '               models.check -> hosts.serve <NODE>'
  Write-Host '  Hermes: models.check -> agents.hermes (license-gated)'
  Write-Host 'NOT DONE YET - FreeBSD llama.cpp 0.7.0 on angel: neither a FreeBSD build nor a'
  Write-Host 'model-load smoke test has been run; angel is still unmeasured and cannot host graph nodes.'
  Write-Host 'After this checkout is available on angel, from code-bootstraps-llama.cpp:'
  Write-Host '  BUILD_DIR=build-freebsd GPU=off scripts/build-linux.sh'
  Write-Host 'Then verify build-freebsd/bin/llama-server --version, measure angel, and re-check graph.yaml.'
  Write-Host ''
}

function ListItems {
  Write-Host 'familia menu items (Windows). Run one with: familia.cmd -Run KEY [ARG...]'
  ShowWorkflowPaths
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

if (-not (Get-Command python -CommandType Application -ErrorAction SilentlyContinue)) {
  # Linux/macOS pwsh (and some Windows installs) only ship python3 or the py launcher.
  $alt = Get-Command python3, py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($alt) { $script:PyExe = $alt.Source; function python { & $script:PyExe @args } }
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Host 'familia-menu: python was not found. Install Python 3 from python.org (tick "Add to PATH"), then run familia.cmd again.'
  exit 1
}
# ---- familia.cmd COMMAND [VALUE...] [ARG...]: the same names as ./familia (scripts\cli-commands.txt) ----
function Tokens($s) {
  $t = @(); if (-not $s) { return ,$t }
  foreach ($m in [regex]::Matches($s, '"([^"]*)"|(\S+)')) { if ($m.Groups[1].Success) { $t += $m.Groups[1].Value } else { $t += $m.Groups[2].Value } }
  return ,$t
}
if ($Cli) {
  $script:Me = 'familia'
  $a = Tokens $env:FAMILIA_CLI_ARGS
  $k = 0; $wantHelp = $false
  while ($k -lt $a.Count -and $a[$k].StartsWith('-')) {
    switch -regex ($a[$k]) {
      '^(-n|--dry-run|-DryRun)$' { $DryRun = $true }
      '^(-y|--yes|-Yes)$' { $env:FAMILIA_ACCEPT_LICENSES = 'yes' }
      '^(--pipe|-Pipe)$' { $env:FAMILIA_MENU_PIPE = '1'; $Pipe = $true }
      '^(--list|-List)$' { $List = $true }
      '^(--run|-Run)$' { $k++; if ($k -lt $a.Count) { $Run = $a[$k] } }
      '^(--search|-Search)$' { $k++; if ($k -lt $a.Count) { $Search = $a[$k] } }
      '^(-h|--help|-Help|-\?)$' { $wantHelp = $true }
      default { Write-Host "familia: unknown option '$($a[$k])'. See: familia.cmd help"; exit 2 }
    }
    $k++
  }
  $rest = @(); if ($k -lt $a.Count) { $rest = @($a[$k..($a.Count - 1)]) }
  if ($wantHelp) { & python scripts/familia_cli.py help --windows | Out-Host; exit 0 }
  if ($Run -or $Search -or $List) {  # the old flag style: -Run KEY [ARG...] [-DryRun] [-Yes]
    $RunArgs = @(); foreach ($x in $rest) {
      if ($x -eq '-DryRun') { $DryRun = $true } elseif ($x -eq '-Yes') { $env:FAMILIA_ACCEPT_LICENSES = 'yes' } else { $RunArgs += $x } }
  } elseif ($rest.Count -gt 0) {
    $w = $rest[0]; $more = @(); if ($rest.Count -gt 1) { $more = @($rest[1..($rest.Count - 1)]) }
    switch ($w) {
      'help' {
        if ($more -contains '--man') {
          Write-Host 'The manual page is man\familia.1. Read it with: man ./man/familia.1 (Git Bash or WSL). The same commands:'
          $more = @()
        }
        & python scripts/familia_cli.py help --windows @more | Out-Host; exit $LASTEXITCODE
      }
      'list' { ListItems; exit 0 }
      'menu' { break }
      'completion' { Write-Host 'familia: completion is for bash (./familia completion bash).'; exit 2 }
      'run' { if (-not $more) { Write-Host 'familia: usage: familia.cmd run KEY [ARG...]'; exit 2 }
              $Run = $more[0]; $RunArgs = @(); if ($more.Count -gt 1) { $RunArgs = @($more[1..($more.Count - 1)]) } }
      'search' {
        if (-not $more) { Write-Host 'familia: usage: familia.cmd search WORD [--run N]'; exit 2 }
        $Search = $more[0]; $RunArgs = @()
        for ($i = 1; $i -lt $more.Count; $i++) {
          if ($more[$i] -match '^(--run|-Run)$' -and $i + 1 -lt $more.Count) { $Run = $more[$i + 1]; $i++ } else { $RunArgs += $more[$i] } }
      }
      default {
        $r = (& python scripts/familia_cli.py resolve --windows @rest | Select-Object -First 1)
        if ($r -match '^item (\S+) (\d+)$') {
          $key = $matches[1]; $n = [int]$matches[2]
          $script:CliHint = 'familia.cmd ' + ($rest[0..($n - 1)] -join ' ')
          $vals = @(); if ($rest.Count -gt $n) { $vals = @($rest[$n..($rest.Count - 1)]) }
          if ($vals.Count -gt 0 -and $vals[0] -match '^(-h|--help)$') { & python scripts/familia_cli.py help --windows @($rest[0..($n - 1)]) | Out-Host; exit 0 }
          exit (RunItem $key $vals $false)
        }
        if ($r -match '^raw (\d+) (\S+) (.*)$') {
          $n = [int]$matches[1]; $gate = $matches[2]; $cmd = $matches[3]
          if ($rest.Count -gt $n) { foreach ($x in $rest[$n..($rest.Count - 1)]) { $cmd += ' ' + (Quote $x) } }
          exit (RunCmd $gate $cmd)
        }
        $p = (& python scripts/familia_cli.py resolve @rest | Select-Object -First 1)
        if ($p -and $p -ne 'none') { Write-Host "familia: '$($rest -join ' ')' runs only on Linux, Android or FreeBSD (./familia). See: familia.cmd help"; exit 2 }
        Write-Host "familia: unknown command '$($rest -join ' ')'. Try: familia.cmd help, or: familia.cmd search $w"; exit 2
      }
    }
  }
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
$showPaths = $true
while ($true) {
  Write-Host ''
  if ($showPaths) { ShowWorkflowPaths; $showPaths = $false }
  Write-Host 'familia: what do you want to do?'
  for ($n = 0; $n -lt $groups.Count; $n++) { Write-Host ('  {0}) {1,-36} {2}' -f ($n + 1), $groups[$n], $groupDesc[$groups[$n]]) }
  Write-Host '  q) Quit      /word search every group (n/N next/previous match)'
  $c = Read-Host "Choose 1-$($groups.Count), /search or q"
  if ($c -eq $null -or $c -eq 'q') { exit 0 }
  $sr = SearchKey $c; if ($sr -eq 'quit') { exit 0 }; if ($sr -eq 'done') { continue }
  if (-not ($c -match '^\d+$') -or [int]$c -lt 1 -or [int]$c -gt $groups.Count) { Write-Host "'$c' isn't one of the choices. Type a number, /word to search, or q."; continue }
  $g = $groups[[int]$c - 1]
  $gi = @(); foreach ($i in $items) { if ($i.Group -eq $g) { $gi += $i } }
  $pageSize = 7; $page = 0
  $pages = [math]::Ceiling($gi.Count / [double]$pageSize)
  while ($true) {
    Write-Host ''; Write-Host "${g}: $($groupDesc[$g])"
    $start = $page * $pageSize
    $end = [math]::Min($start + $pageSize, $gi.Count)
    if ($pages -gt 1) { Write-Host ('  Page {0} of {1} (items {2}-{3} of {4})' -f ($page + 1), $pages, ($start + 1), $end, $gi.Count) }
    for ($idx = $start; $idx -lt $end; $idx++) {
      $note = ''; if (-not (NeedOk $gi[$idx].Need)) { $note = ' (not available yet)' }
      Write-Host ('  {0}) {1}{2}' -f ($idx - $start + 1), $gi[$idx].Label, $note)
      Write-Host ('       runs: {0}' -f (Shown $gi[$idx].Cmd))
    }
    if ($pages -gt 1) {
      if ($page -gt 0) { Write-Host '  <) Previous page' }
      if ($page -lt ($pages - 1)) { Write-Host '  >) Next page' }
    }
    Write-Host '  b) Back      /word search every group (n/N next/previous match)'
    if ($pages -gt 1) { $c = Read-Host "Choose 1-$($end - $start), </> page, /search or b" }
    else { $c = Read-Host "Choose 1-$($gi.Count), /search or b" }
    if ($c -eq $null -or $c -eq 'b' -or $c -eq '') { break }
    if ($c -eq 'q') { exit 0 }
    if ($c -eq '>' -or $c -eq 'next') { if ($page -lt ($pages - 1)) { $page++ }; continue }
    if ($c -eq '<' -or $c -eq 'prev') { if ($page -gt 0) { $page-- }; continue }
    $sr = SearchKey $c; if ($sr -eq 'quit') { exit 0 }; if ($sr -eq 'done') { continue }
    if (-not ($c -match '^\d+$') -or [int]$c -lt 1 -or [int]$c -gt ($end - $start)) {
      if ($pages -gt 1) { Write-Host "'$c' isn't one of the choices. Type a number, </> page, /word to search, or b." }
      else { Write-Host "'$c' isn't one of the choices. Type a number, /word to search, or b." }
      continue
    }
    $selected = $start + [int]$c - 1
    $rc = RunItem $gi[$selected].Key @() $true
    if ($rc) { Write-Host "(that step exited with status $rc)" }
  }
}
