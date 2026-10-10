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
  [string]$Branch = 'main',
  [string]$ModelsPath,
  [switch]$NoRuntime,
  [switch]$ForceHost,
  [switch]$LogonTask,
  [string]$Model
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
if (Test-Path (Join-Path $repo '.git')) {
  if ($PSCmdlet.ShouldProcess($repo, 'git pull --ff-only')) { & git -C $repo pull --ff-only -q; if ($LASTEXITCODE) { Say 'warning: repo not fast-forwardable; left as is' } }
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
    if ($LASTEXITCODE -eq 0) { & python (Join-Path $repo 'scripts\validate_graph.py') --no-files $graph; if ($LASTEXITCODE) { Say 'warning: graph validation reported problems' } }
    else { Say 'PyYAML missing: graph validation skipped (pip install pyyaml)' }
  } else { Say 'python not found: graph validation skipped' }
} else { Say "graph.yaml not present yet (dry-run?): would measure into $graph" }

# 4. optional per-user logon task (no admin) via the existing #17 script
if ($LogonTask) {
  if (-not $Model) { throw '-LogonTask needs -Model <gguf name>' }
  $task = Join-Path $repo 'scripts\windows\install-task.ps1'
  $rt = if (Test-Path (Join-Path $runtimeRoot 'current.txt')) { (Get-Content (Join-Path $runtimeRoot 'current.txt')).Trim() } else { $null }
  if (Test-Path $task) { & $task -Install -Model $Model -ModelsPath $ModelsPath -RuntimePath $rt -WhatIf:$dry }
  else { Say "would register logon task via $task" }
}
Say "done. Start a node: set FAMILIA_RUNTIME to the runtime dir and FAMILIA_MODEL, then run $repo\scripts\windows\start.bat"
