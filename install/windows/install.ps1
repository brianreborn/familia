<#
.SYNOPSIS
  familia one-click installer for Windows 10/11 (per-user, no admin).
.DESCRIPTION
  Installs to %LOCALAPPDATA%\familia (override -Prefix). Clones the repo (git required,
  or downloads the branch zip when git is missing), downloads the official ggml-org
  llama.cpp CPU build (win-cpu-x64: picks its CPU backend at runtime, works without AVX),
  verifies it against the sha256 digest the GitHub release API publishes at install time
  (no hardcoded hashes; refuses when no digest is published), measures this host into
  graph.yaml as hosts.<name>, validates the graph when Python+PyYAML exist, and
  optionally registers the per-user logon task (scripts\windows\install-task.ps1).
  Idempotent: re-running skips what is already in place.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install\windows\install.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install\windows\install.ps1 -DryRun
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install\windows\install.ps1 -Uninstall
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install\windows\install.ps1 -Yes
  (-Yes accepts the license review without a prompt; the summary is still printed.
   -AcceptUnknown also accepts items whose license could not be found. See docs\licenses.md.)
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install\windows\install.ps1 -NoPath
  (by default `familia` is put on your user PATH: a 2-line shim in %LOCALAPPDATA%\Programs\familia\bin
   plus HKCU\Environment, no admin; see scripts\windows\install-cli.ps1. -NoPath skips that.)
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [switch]$DryRun,
  [switch]$Uninstall,
  [switch]$Purge,
  [string]$Prefix = (Join-Path $env:LOCALAPPDATA 'familia'),
  [string]$Name = ($env:COMPUTERNAME).ToLower(),
  [string]$Build = 'b11539',
  [string]$RepoUrl = 'https://github.com/brianreborn/familia.git',
  [string]$Branch = $env:FAMILIA_BRANCH,
  [string]$ModelsPath,
  [switch]$NoRuntime,
  [switch]$ForceHost,
  [switch]$LogonTask,
  [string]$Model,
  [switch]$Yes,
  [switch]$AcceptUnknown,
  [switch]$NoPath
)
$ErrorActionPreference = 'Stop'
Import-Module CimCmdlets -Verbose:$false  # load before WhatIf so module aliases are not reported
if ($DryRun) { $WhatIfPreference = $true }
$dry = [bool]$WhatIfPreference
function Say([string]$m) { Write-Host "familia-install: $m" }
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$repo = Join-Path $Prefix 'repo'
$runtimeRoot = Join-Path $Prefix 'runtime'
if (-not $ModelsPath) {
  if (Test-Path 'E:\temp\') { $ModelsPath = 'E:\temp\familia\models' } else { $ModelsPath = Join-Path $Prefix 'models' }
}

if ($Uninstall) {
  $task = Join-Path $repo 'scripts\windows\install-task.ps1'
  if (Test-Path $task) { & $task -Uninstall -WhatIf:$dry }
  $cli = Join-Path $repo 'scripts\windows\install-cli.ps1'
  if (Test-Path $cli) { & $cli -Uninstall -WhatIf:$dry }  # shim + PATH entry, exactly what it recorded
  foreach ($p in @($repo, $runtimeRoot)) {
    if ((Test-Path $p) -and $PSCmdlet.ShouldProcess($p, 'Remove')) { Remove-Item -Recurse -Force $p }
  }
  if ($Purge -and (Test-Path $Prefix) -and $PSCmdlet.ShouldProcess($Prefix, 'Remove (purge)')) { Remove-Item -Recurse -Force $Prefix }
  Say "uninstalled (models in $ModelsPath kept)"
  return
}

if ($Name -notmatch '^[a-z0-9][a-z0-9_-]*$') { throw "invalid -Name '$Name' (use [a-z0-9_-])" }
Say "prefix $Prefix, host $Name, models $ModelsPath, dry-run=$dry"
foreach ($d in @($Prefix, $runtimeRoot, $ModelsPath)) {
  if (-not (Test-Path $d) -and $PSCmdlet.ShouldProcess($d, 'Create directory')) { New-Item -ItemType Directory -Force $d | Out-Null }
}

# 1. repo
$git = Get-Command git -ErrorAction SilentlyContinue
$selectBranch = -not [string]::IsNullOrWhiteSpace($Branch)
if (-not $selectBranch) {
  $sourceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
  if ($git -and (Test-Path (Join-Path $sourceRoot '.git'))) {
    $sourceBranch = (& git -C $sourceRoot branch --show-current 2>$null).Trim()
    if ($LASTEXITCODE -eq 0 -and $sourceBranch) { $Branch = $sourceBranch; $selectBranch = $true }
  }
}
if (-not $Branch) { $Branch = 'main' }
if (Test-Path (Join-Path $repo '.git')) {
  if ($selectBranch) {
    if ($PSCmdlet.ShouldProcess($repo, "switch to track origin/$Branch and fast-forward only")) {
      & git -C $repo fetch -q origin "+refs/heads/${Branch}:refs/remotes/origin/${Branch}"
      if ($LASTEXITCODE) { throw "could not fetch origin/$Branch" }
      & git -C $repo show-ref --verify --quiet "refs/heads/$Branch"
      if ($LASTEXITCODE -eq 0) { & git -C $repo switch $Branch }
      else { & git -C $repo switch --track -c $Branch "origin/$Branch" }
      if ($LASTEXITCODE) { throw "could not switch to $Branch; check for local changes or branch conflicts" }
      & git -C $repo branch "--set-upstream-to=origin/$Branch" $Branch
      if ($LASTEXITCODE) { throw "could not set $Branch to track origin/$Branch" }
      & git -C $repo merge --ff-only "origin/$Branch"
      if ($LASTEXITCODE) { throw "repo branch $Branch could not be fast-forwarded; local changes were preserved" }
    }
  } elseif ($PSCmdlet.ShouldProcess($repo, 'git pull --ff-only')) {
    & git -C $repo pull --ff-only -q
    if ($LASTEXITCODE) { Say 'warning: repo not fast-forwardable; left as is' }
  }
} elseif (-not (Test-Path $repo)) {
  if ($git) {
    if ($PSCmdlet.ShouldProcess($repo, "git clone $RepoUrl ($Branch)")) { & git clone -q --branch $Branch $RepoUrl $repo; if ($LASTEXITCODE) { throw 'git clone failed' } }
  } else {
    $zipUrl = ($RepoUrl -replace '\.git$', '') + "/archive/refs/heads/$Branch.zip"
    if ($PSCmdlet.ShouldProcess($repo, "download $zipUrl (git not found; no updates via pull)")) {
      $tmpz = Join-Path $env:TEMP "familia-$Branch.zip"
      Invoke-WebRequest -UseBasicParsing $zipUrl -OutFile $tmpz
      $ex = Join-Path $env:TEMP 'familia-src'; Expand-Archive -Force $tmpz $ex
      Move-Item (Get-ChildItem $ex | Select-Object -First 1).FullName $repo
      Remove-Item -Recurse -Force $ex, $tmpz
    }
  }
}

# Licenses before anything else is downloaded (docs\licenses.md)
if ($Yes) { $env:FAMILIA_ACCEPT_LICENSES = 'yes' }
if ($AcceptUnknown) { $env:FAMILIA_ACCEPT_UNKNOWN_LICENSES = 'yes' }
$lic = Join-Path $repo 'scripts\licenses.py'
if ($dry) { Say "would show the license review: python $lic gate" }
elseif (Test-Path $lic) {
  if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $lic gate
    if ($LASTEXITCODE) { throw "licenses not accepted; nothing else was downloaded. Review: python $lic review (or re-run with -Yes, plus -AcceptUnknown)" }
  } elseif ($env:FAMILIA_ACCEPT_LICENSES -ne 'yes') {
    throw "python not found, so the license review can't run. Install Python 3, or read docs\licenses.md and re-run with -Yes."
  }
}
# Every pinned part to its pin, together (scripts\sync_pins.py); again after each later git pull.
$sync = Join-Path $repo 'scripts\sync_pins.py'
if ($dry) { Say "would sync the pinned parts: python $sync" }
elseif ((Test-Path $sync) -and (Get-Command python -ErrorAction SilentlyContinue)) {
  & python $sync --root $repo
  if ($LASTEXITCODE) { throw 'the pinned parts could not be synced (see above)' }
  & python $sync --root $repo --install-hooks | Out-Null
}

# 2. llama.cpp CPU runtime, verified against the release API digest
if (-not $NoRuntime) {
  $api = 'https://api.github.com/repos/ggml-org/llama.cpp/releases'
  if ($Build -eq 'latest') { $rels = Invoke-RestMethod -UseBasicParsing "$api`?per_page=30" -Headers @{ Accept = 'application/vnd.github+json' } }
  else { $rels = @(Invoke-RestMethod -UseBasicParsing "$api/tags/$Build" -Headers @{ Accept = 'application/vnd.github+json' }) }
  $asset = $null; $tag = $null
  foreach ($r in $rels) {
    if ($r.tag_name -notmatch '^b\d+$') { continue }
    $a = $r.assets | Where-Object { $_.name -match 'bin-win-cpu-x64\.zip$' } | Select-Object -First 1
    if ($a) { $asset = $a; $tag = $r.tag_name; break }
  }
  if (-not $asset) { throw "no win-cpu-x64 asset found for build $Build" }
  $digest = [string]$asset.digest
  if ($digest -notmatch '^sha256:([0-9a-f]{64})$') { throw "release API published no sha256 digest for $($asset.name); refusing unverified download" }
  $want = $Matches[1]
  $dest = Join-Path $runtimeRoot $tag
  if (Test-Path (Join-Path $dest 'llama-server.exe')) { Say "runtime $tag already installed" }
  elseif ($PSCmdlet.ShouldProcess($dest, "download $($asset.browser_download_url), verify sha256 $want, extract")) {
    $tmp = Join-Path $env:TEMP $asset.name
    Invoke-WebRequest -UseBasicParsing $asset.browser_download_url -OutFile $tmp
    $got = (Get-FileHash -Algorithm SHA256 $tmp).Hash.ToLower()
    if ($got -ne $want) { Remove-Item -Force $tmp; throw "sha256 mismatch for $($asset.name): got $got want $want" }
    Say "sha256 ok ($want)"
    Expand-Archive -Force $tmp $dest
    Remove-Item -Force $tmp
    $exe = Get-ChildItem -Recurse $dest -Filter llama-server.exe | Select-Object -First 1
    if (-not $exe) { throw 'llama-server.exe missing from archive' }
    if ($exe.DirectoryName -ne $dest) { Get-ChildItem $exe.DirectoryName | Move-Item -Destination $dest -Force }
  }
  $cur = Join-Path $runtimeRoot 'current.txt'
  if ($PSCmdlet.ShouldProcess($cur, "record current runtime $tag")) { Set-Content -Encoding ascii $cur $dest }
}

# 3. measured host entry (only values read from this machine; never guessed)
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$osi = Get-CimInstance Win32_OperatingSystem
$ram = [int]([math]::Floor($cs.TotalPhysicalMemory / 1MB))
$kind = 'desktop'; if (Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue) { $kind = 'laptop' }
$reserve = 3072; if ($ram -ge 12288) { $reserve = 4096 }
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm zzz'
$cpuName = ($cpu.Name.Trim()) -replace "'", "''"
$block = @(
  "  ${Name}:",
  "    kind: $kind",
  "    measured: true",
  "    measured_at: '$stamp'",
  "    measured_by: install/windows/install.ps1",
  "    os: windows",
  "    cpu: '$cpuName'",
  "    threads: $($cs.NumberOfLogicalProcessors)",
  "    ram_mib: $ram",
  "    reserve_ram_mib: $reserve                # policy (installer default), not measured; see docs/ram-safety.md",
  "    gpus: []                     # not probed by installer; add after measuring",
  "    notes: '$($osi.Caption) $($osi.Version)'"
) -join "`n"
Write-Host $block
$graph = Join-Path $repo 'graph.yaml'
if (Test-Path $graph) {
  $text = [IO.File]::ReadAllText($graph) -replace "`r`n", "`n"
  $m = [regex]::Match($text, '(?m)^hosts:[ \t]*\n')
  if (-not $m.Success) { throw 'graph.yaml has no top-level hosts:' }
  $start = $m.Index + $m.Length
  $e = [regex]::Match($text.Substring($start), '(?m)^\S')
  $end = if ($e.Success) { $start + $e.Index } else { $text.Length }
  $sect = $text.Substring($start, $end - $start)
  $h = [regex]::Match($sect, "(?m)^  $([regex]::Escape($Name)):[ \t]*\n")
  $new = $null
  if ($h.Success) {
    if ($ForceHost) {
      $rest = $sect.Substring($h.Index + $h.Length)
      $n = [regex]::Match($rest, '(?m)^  \S')
      $hend = if ($n.Success) { $h.Index + $h.Length + $n.Index } else { $h.Index + $h.Length + $rest.TrimEnd("`n").Length + 1 }
      $sect = $sect.Substring(0, $h.Index) + $block + "`n" + $sect.Substring($hend)
      $new = $text.Substring(0, $start) + $sect + $text.Substring($end)
    } else { Say "hosts.$Name exists; left unchanged (use -ForceHost to replace)" }
  } else {
    $body = $sect.TrimEnd("`n") + "`n"
    $new = $text.Substring(0, $start) + $body + $block + "`n" + $sect.Substring($body.Length) + $text.Substring($end)
  }
  if ($new -and $PSCmdlet.ShouldProcess($graph, "write hosts.$Name")) {
    [IO.File]::WriteAllText($graph, $new, (New-Object Text.UTF8Encoding $false))
    Say "wrote hosts.$Name"
  }
  $py = Get-Command python -ErrorAction SilentlyContinue
  if ($py) {
    & python -c 'import yaml' 2>$null
    if ($LASTEXITCODE -eq 0) { & python (Join-Path $repo 'scripts\validate_graph.py') --no-files --graph $graph; if ($LASTEXITCODE) { Say 'warning: graph validation reported problems' } }
    else { Say 'PyYAML missing: graph validation skipped (pip install pyyaml)' }
  } else { Say 'python not found: graph validation skipped' }
  if ($py) {
    # numpy (LittleBit runtime): spec depends only on the x86-64 level (scripts\cpu_level.py)
    # pre-v2 x86: our cpu-baseline=none numpy 2.x wheel from the release first, then numpy<2.4
    $cands = @(& python (Join-Path $repo 'scripts\cpu_level.py') --numpy-candidates 2>$null | Where-Object { $_ }); if (-not $cands) { $cands = @('numpy') }
    & python -c 'import numpy' 2>$null
    if ($LASTEXITCODE -and $PSCmdlet.ShouldProcess('python', "pip install --user $($cands -join ' || ')")) {
      $ok = $false
      foreach ($np in $cands) { & python -m pip install --user --quiet --no-warn-script-location $np; if (-not $LASTEXITCODE) { & python -c 'import numpy' 2>$null; if (-not $LASTEXITCODE) { $ok = $true; break } } }
      if (-not $ok) { Say "note: numpy not installed (optional; pip install --user $($cands[-1]))" }
    }
  }
} else { Say "graph.yaml not present yet (dry-run?): would measure into $graph" }

# 4. optional per-user logon task (no admin) via the existing #17 script
if ($LogonTask) {
  if (-not $Model) { throw '-LogonTask needs -Model <gguf name>' }
  $task = Join-Path $repo 'scripts\windows\install-task.ps1'
  $rt = if (Test-Path (Join-Path $runtimeRoot 'current.txt')) { (Get-Content (Join-Path $runtimeRoot 'current.txt')).Trim() } else { $null }
  if (Test-Path $task) { & $task -Install -Model $Model -ModelsPath $ModelsPath -RuntimePath $rt -WhatIf:$dry }
  else { Say "would register logon task via $task" }
}
# 5. `familia` on the user PATH: 2-line shim + HKCU\Environment (no admin); -NoPath skips
$cli = Join-Path $repo 'scripts\windows\install-cli.ps1'
if (Test-Path $cli) { & $cli -NoPath:$NoPath -WhatIf:$dry }
else { Say "would put familia on PATH via $cli" }
Say "done. Start a node: set FAMILIA_RUNTIME to the runtime dir and FAMILIA_MODEL, then run $repo\scripts\windows\start.bat"
Say "what now: run $repo\familia.cmd for the menu (Skills, Models, licenses). Quick start: $repo\QUICKSTART.md"
