<#
.SYNOPSIS
  Put `familia` on your PATH for this Windows user (no admin). The code stays in this checkout.
.DESCRIPTION
  Writes a 2-line shim %LOCALAPPDATA%\Programs\familia\bin\familia.cmd that runs this checkout's
  familia.cmd, and adds that bin folder to the user PATH (HKCU\Environment, value type kept as
  REG_EXPAND_SZ). Every file written, and the PATH entry if this script added it, is recorded in
  <Prefix>\installed.txt; -Uninstall removes exactly those. -WhatIf previews and changes nothing.
  -NoPath writes the shim but leaves PATH alone (prints what to add instead).
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-cli.ps1 -WhatIf
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-cli.ps1
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-cli.ps1 -Uninstall -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$Prefix = (Join-Path $env:LOCALAPPDATA 'Programs\familia'),
  [switch]$Uninstall,
  [switch]$Status,
  [switch]$NoPath,
  [switch]$Force,
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
if ($DryRun) { $WhatIfPreference = $true }
function Say([string]$m) { Write-Host "familia-cli: $m" }
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$bin = Join-Path $Prefix 'bin'
$shim = Join-Path $bin 'familia.cmd'
$manifest = Join-Path $Prefix 'installed.txt'
$want = "@echo off`r`n`"$root\familia.cmd`" %*`r`n"

function Get-UserPath {
  $k = Get-Item 'HKCU:\Environment'
  return [string]$k.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
}
function Set-UserPath([string]$v) {
  New-ItemProperty -Path 'HKCU:\Environment' -Name Path -Value $v -PropertyType ExpandString -Force -WhatIf:$false | Out-Null
  # tell Explorer and new consoles that the environment changed (what SetEnvironmentVariable does)
  if (-not ('Familia.Env' -as [type])) {
    Add-Type -Namespace Familia -Name Env -MemberDefinition '[DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern System.IntPtr SendMessageTimeout(System.IntPtr h, uint m, System.UIntPtr w, string l, uint f, uint t, out System.UIntPtr r);'
  }
  $r = [UIntPtr]::Zero
  [void][Familia.Env]::SendMessageTimeout([IntPtr]0xffff, 0x1A, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$r)
}
function Test-OnPath([string]$p) { return (@((Get-UserPath) -split ';' | Where-Object { $_.TrimEnd('\') -ieq $bin.TrimEnd('\') }).Count -gt 0) }
function Test-Shim([string]$f) { return ((Test-Path $f) -and ((Get-Content -Raw $f) -match '^@echo off\r?\n"[^"]*\\familia\.cmd" %\*\r?\n?$')) }
function Get-Manifest { if (Test-Path $manifest) { return @(Get-Content $manifest | Where-Object { $_ }) } else { return @() } }
function Add-Record([string]$line) {
  if ($WhatIfPreference) { return }
  if ((Get-Manifest) -notcontains $line) { Add-Content -Path $manifest -Value $line -WhatIf:$false }
}

if ($Status) {
  if (Test-Shim $shim) { Say "shim: $shim" } else { Say "shim: not installed ($shim)" }
  if (Test-OnPath $bin) { Say "user PATH: has $bin" } else { Say "user PATH: does not have $bin" }
  Say "manifest $manifest :"; Get-Manifest | ForEach-Object { Write-Host "    $_" }
  return
}

if ($Uninstall) {
  $m = Get-Manifest
  if (-not $m) { Say "nothing recorded in $manifest; nothing to remove"; return }
  foreach ($line in $m) {
    if ($line -like 'PATH:*') {
      $dir = $line.Substring(5)
      if ($PSCmdlet.ShouldProcess('user PATH (HKCU\Environment)', "remove $dir")) {
        $rest = @((Get-UserPath) -split ';' | Where-Object { $_ -and ($_.TrimEnd('\') -ine $dir.TrimEnd('\')) })
        Set-UserPath ($rest -join ';'); Say "removed $dir from the user PATH"
      }
    } elseif (Test-Shim $line) {
      if ($PSCmdlet.ShouldProcess($line, 'Remove')) { Remove-Item -Force $line; Say "removed $line" }
    } elseif (Test-Path $line) { Say "keep $line (changed since install; not a familia shim)" }
  }
  if ($PSCmdlet.ShouldProcess($manifest, 'Remove')) {
    Remove-Item -Force $manifest
    foreach ($d in @($bin, $Prefix)) { if ((Test-Path $d) -and -not (Get-ChildItem -Force $d)) { Remove-Item $d } }
    Say "uninstalled; the checkout $root was not touched"
  }
  return
}

if (-not (Test-Path (Join-Path $root 'familia.cmd'))) { throw "$root\familia.cmd is missing" }
Say "checkout: $root (the code stays here; nothing is copied)"
if ((Test-Path $shim) -and ((Get-Content -Raw $shim) -eq $want)) { Say "up to date: $shim"; Add-Record $shim }
else {
  if ((Test-Path $shim) -and -not (Test-Shim $shim) -and -not $Force) { throw "$shim exists and is not a familia shim; move it away or use -Force" }
  if ($PSCmdlet.ShouldProcess($shim, "Write 2-line shim -> $root\familia.cmd")) {
    if (-not (Test-Path $bin)) { New-Item -ItemType Directory -Force $bin | Out-Null }
    [IO.File]::WriteAllText($shim, $want, [Text.Encoding]::ASCII)
    Add-Record $shim; Say "wrote $shim"
  }
}
if (Test-OnPath $bin) { Say "$bin is already on your user PATH" }
elseif ($NoPath) { Say "-NoPath: user PATH left alone. To add it yourself: setx is NOT safe for long PATHs; use Settings > 'Edit environment variables for your account' and add $bin" }
elseif ($PSCmdlet.ShouldProcess('user PATH (HKCU\Environment)', "append $bin")) {
  $cur = (Get-UserPath).TrimEnd(';')
  Set-UserPath $(if ($cur) { "$cur;$bin" } else { $bin })
  Add-Record "PATH:$bin"
  Say "added $bin to your user PATH; open a new console window to use 'familia'"
}
