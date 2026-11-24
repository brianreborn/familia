<#
.SYNOPSIS
  Windows home menu (mirrors scripts/familia_home.sh).
  Talk to the protomodel is item 1. The six areas stay equal. Legacy menu is last.
  Numbered: arrows and digits. gum is used only when it accepts --numbered.
  No gum falls back to the legacy menu. -ListGoals / --list-goals prints and exits.
  No tty (redirected stdin or FAMILIA_NO_TTY=1) opens the legacy numeric menu.
  CI=true alone does not force that. Ctrl-C, Esc and EOF in a submenu return
  to this menu; at this menu they exit 0.
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\familia-home.ps1
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\familia-home.ps1 -ListGoals
#>
param(
  [switch]$ListGoals,
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)
$ErrorActionPreference = 'Stop'
$script:Interrupted = $false
$script:GumFails = 0
# trap { continue } does not see Ctrl-C. CancelKeyPress does.
try {
  [Console]::TreatControlCAsInput = $false
  $onCtrlC = {
    param($sender, $eventArgs)
    $eventArgs.Cancel = $true
    $script:Interrupted = $true
    Write-Host ''
    Write-Host 'familia-home: interrupted; staying in the menu. Choose Quit to leave.'
  }
  [Console]::add_CancelKeyPress($onCtrlC)
} catch {
  Write-Host 'familia-home: Ctrl-C handler was not installed'
}
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

$wantList = [bool]$ListGoals
if ($Rest) {
  foreach ($a in $Rest) {
    if ($a -eq '--list-goals' -or $a -eq '-l' -or $a -eq '-ListGoals') { $wantList = $true }
  }
}
if ($wantList) { Show-Goals }

function Test-NoStdin {
  # stdin redirected, or FAMILIA_NO_TTY=1. Do not consult CI.
  if ($env:FAMILIA_NO_TTY -eq '1') { return $true }
  try { return [Console]::IsInputRedirected } catch { return $false }
}

if (Test-NoStdin) {
  Write-Host 'familia-home: no terminal; opening the legacy numeric menu.'
  $env:FAMILIA_NO_TTY = '1'
  $menu = Join-Path $root 'scripts\windows\familia-menu.ps1'
  & powershell -NoProfile -ExecutionPolicy Bypass -File $menu -Pipe
  exit $LASTEXITCODE
}

function Enter-Legacy([string]$why) {
  Write-Host "familia-home: $why"
  Write-Host 'familia-home: falling back to the legacy menu. Type q to quit.'
  $menu = Join-Path $root 'scripts\windows\familia-menu.ps1'
  & powershell -NoProfile -ExecutionPolicy Bypass -File $menu
  exit $LASTEXITCODE
}

if (-not $script:PyExe) { Enter-Legacy 'python was not found' }

function Test-GumUsable {
  $cmd = Get-Command gum -ErrorAction SilentlyContinue
  if (-not $cmd) { return $false }
  & gum --version *> $null
  if ($LASTEXITCODE -ne 0) { return $false }
  $help = (& gum choose --help 2>&1 | Out-String)
  return ($help -match '--header' -and $help -match '--height')
}

if (-not (Get-Command gum -ErrorAction SilentlyContinue)) {
  if ($env:FAMILIA_SKIP_GUM_INSTALL -ne '1') {
    $inst = Join-Path $root 'scripts\windows\install-gum.ps1'
    if ((Test-Path $inst) -and [Environment]::UserInteractive) {
      try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $inst
      } catch {
        Write-Host 'familia-home: gum install did not finish'
      }
      $bin = Join-Path $env:LOCALAPPDATA 'Programs\familia\bin'
      $env:Path = "$bin;$env:Path"
    }
  }
}
if (-not (Test-GumUsable)) {
  Enter-Legacy 'gum is missing, too old, or failed its version check'
}

function Show-Banner {
  Write-Host '  +------------------------------------------------------------------+'
  Write-Host '  | familia   Talk first   six equal items   Legacy menu last        |'
  Write-Host '  +------------------------------------------------------------------+'
}

function Test-GumNumbers {
  if (-not (Test-GumUsable)) { return $false }
  $help = (& gum choose --help 2>&1 | Out-String)
  return ($help -match '--numbered')
}

function Read-HomeChoice([string]$header, [string[]]$options) {
  Write-Host $header
  if (Test-GumNumbers) {
    $sel = & gum choose --numbered --header $header --height 16 @options
    if ($LASTEXITCODE -eq 0 -and $sel) { return @{ Code = 0; Value = [string]$sel } }
    if ($LASTEXITCODE -eq 130) { return @{ Code = 130; Value = '' } }
    return @{ Code = 3; Value = '' }
  }
  $idx = 0
  $typed = ''
  $old = $false
  try { $old = [Console]::TreatControlCAsInput } catch { $old = $false }
  try { [Console]::TreatControlCAsInput = $true } catch { }
  try {
    while ($true) {
      Write-Host ''
      for ($i = 0; $i -lt $options.Count; $i++) {
        $mark = ' '
        if ($i -eq $idx) { $mark = '>' }
        Write-Host ('{0} {1,2}) {2}' -f $mark, ($i + 1), $options[$i])
      }
      Write-Host 'Number and Enter, or arrows. q quits. Esc goes back.'
      $key = $null
      try { $key = [Console]::ReadKey($true) } catch { return @{ Code = 4; Value = '' } }
      if ($null -eq $key) { return @{ Code = 4; Value = '' } }
      if ($key.Key -eq 'Escape') { return @{ Code = 3; Value = '' } }
      if ($key.Key -eq 'UpArrow') {
        $idx = ($idx - 1 + $options.Count) % $options.Count
        $typed = ''
        continue
      }
      if ($key.Key -eq 'DownArrow') {
        $idx = ($idx + 1) % $options.Count
        $typed = ''
        continue
      }
      $ctrl = $false
      try { $ctrl = [bool]($key.Modifiers -band [ConsoleModifiers]::Control) } catch { $ctrl = $false }
      if ($ctrl -and ($key.Key -eq 'C')) { return @{ Code = 130; Value = '' } }
      if ($ctrl -and ($key.Key -eq 'D' -or $key.Key -eq 'Z')) { return @{ Code = 4; Value = '' } }
      if ($key.Key -eq 'Enter') {
        if ($typed -match '^\d+$') {
          $n = [int]$typed
          if ($n -ge 1 -and $n -le $options.Count) {
            return @{ Code = 0; Value = $options[$n - 1] }
          }
          Write-Host 'familia-home: that number is not on the menu.'
          $typed = ''
          continue
        }
        return @{ Code = 0; Value = $options[$idx] }
      }
      if (($key.Key -eq 'Q') -and -not $typed) { return @{ Code = 0; Value = 'Quit' } }
      if ($key.KeyChar -ge '0' -and $key.KeyChar -le '9' -and $typed.Length -lt 4) {
        $typed += $key.KeyChar
      }
    }
  } finally {
    try { [Console]::TreatControlCAsInput = $old } catch { }
  }
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

function Read-Required([string]$prompt) {
  try {
    $got = Read-Host $prompt
  } catch {
    Write-Host 'familia-home: not confirmed. Staying in the menu.'
    return $null
  }
  if (-not $got) {
    Write-Host 'familia-home: not confirmed. Staying in the menu.'
    return $null
  }
  return $got
}

function Invoke-Verb([string]$area, [string]$verb) {
  $apply = $false
  $extra = @()
  if ($verb -eq 'install' -or $verb -eq 'start' -or $verb -eq 'stop') {
    try {
      $ans = Read-Host "Run $area $verb now (--apply)? [y/N]"
    } catch {
      Write-Host 'familia-home: interrupted; staying in the menu.'
      return
    }
    if ($ans -eq 'y' -or $ans -eq 'Y' -or $ans -eq 'yes' -or $ans -eq 'YES') {
      $apply = $true
    } else {
      Write-Host 'familia-home: not confirmed. Staying in the menu.'
      return
    }
    if ($area -eq 'models' -and $verb -eq 'install') {
      $extra = @(Read-Required 'Hugging Face repo ORG/NAME (empty cancels)')
      if (-not $extra[0]) { return }
    } elseif (($area -eq 'harnesses') -and ($verb -eq 'start' -or $verb -eq 'stop')) {
      $extra = @(Read-Required 'Agent name (empty cancels)')
      if (-not $extra[0]) { return }
    } elseif ($area -eq 'tools' -and $verb -eq 'install') {
      $extra = @(Read-Required 'Skill id (empty cancels)')
      if (-not $extra[0]) { return }
    }
  }
  $script:Interrupted = $false
  if ($apply) {
    & $script:PyExe (Join-Path $root 'scripts\home_catalog.py') $area $verb '--apply' @extra
  } else {
    & $script:PyExe (Join-Path $root 'scripts\home_catalog.py') $area $verb
  }
  if ($script:Interrupted) {
    Write-Host 'familia-home: interrupted; staying in the menu. Choose Quit to leave.'
  }
  if ($LASTEXITCODE -ne 0) {
    Write-Host "familia-home: $area $verb exited $LASTEXITCODE. Staying in the menu."
  }
}

function Enter-Area([string]$area, [string]$title) {
  while ($true) {
    $picked = Read-HomeChoice "$title : install, list, start, stop, status. Quit leaves." @(
      'install', 'list', 'start', 'stop', 'status', 'Back', 'Quit')
    if ($picked.Code -eq 3 -or $picked.Code -eq 4 -or $picked.Code -eq 130) { return }
    $sel = $picked.Value
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

function Get-HomeItems {
  $lines = & $script:PyExe (Join-Path $root 'scripts\home_catalog.py') --items
  if ($LASTEXITCODE -ne 0 -or -not $lines) {
    Enter-Legacy 'the home catalog failed'
  }
  return @($lines | Where-Object { $_ })
}

$titles = Get-HomeItems
while ($true) {
  Show-Banner
  $picked = Read-HomeChoice 'What do you want to do? Type a number or use arrows. q quits.' $titles
  if ($picked.Code -eq 3 -or $picked.Code -eq 4 -or $picked.Code -eq 130) { exit 0 }
  $sel = $picked.Value
  if (-not $sel) {
    Write-Host 'familia-home: staying in the menu. Choose Quit to leave.'
    continue
  }
  switch ($sel) {
    'Quit' { exit 0 }
    'Talk to the protomodel' {
      $bash = Get-Command bash -ErrorAction SilentlyContinue
      if (-not $bash) { Write-Host 'familia-home: bash is not on PATH. Staying in the menu.'; continue }
      & bash (Join-Path $root 'scripts\proto_chat.sh')
    }
    'Find more models' {
      $bash = Get-Command bash -ErrorAction SilentlyContinue
      if (-not $bash) { Write-Host 'familia-home: bash is not on PATH. Staying in the menu.'; continue }
      & bash (Join-Path $root 'scripts\find_models.sh')
    }
    'Search my X / Twitter posts' {
      $bash = Get-Command bash -ErrorAction SilentlyContinue
      if (-not $bash) { Write-Host 'familia-home: bash is not on PATH. Staying in the menu.'; continue }
      & bash (Join-Path $root 'scripts\search_x.sh')
    }
    'Open llama-ui web cockpit' {
      $bash = Get-Command bash -ErrorAction SilentlyContinue
      if (-not $bash) { Write-Host 'familia-home: bash is not on PATH. Staying in the menu.'; continue }
      $env:FAMILIA_COCKPIT_HOOK = '1'
      & bash (Join-Path $root 'scripts\android-cockpit-switches.sh')
      if ($LASTEXITCODE -eq 4) { & bash (Join-Path $root 'scripts\open_ui.sh') }
    }
    'List all models' {
      & $script:PyExe (Join-Path $root 'scripts\catalog.py') models
    }
    'Configure all graphs' {
      & $script:PyExe (Join-Path $root 'scripts\catalog.py') graphs
    }
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
