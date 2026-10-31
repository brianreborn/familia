<#
.SYNOPSIS
  Put Charm gum.exe on this Windows user's PATH (no admin).
.DESCRIPTION
  Downloads a Charm gum Windows zip into %LOCALAPPDATA%\Programs\familia\bin\gum.exe
  (same bin as the familia shim). Soft-fail friendly for install.ps1.
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-gum.ps1 -WhatIf
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-gum.ps1 -Yes
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$Prefix = (Join-Path $env:LOCALAPPDATA 'Programs\familia'),
  [string]$Version = $(if ($env:FAMILIA_GUM_VERSION) { $env:FAMILIA_GUM_VERSION } else { '2.0.2' }),
  [switch]$Yes,
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
if ($DryRun) { $WhatIfPreference = $true }
function Say([string]$m) { Write-Host "install-gum: $m" }
$Version = $Version.TrimStart('v')
$bin = Join-Path $Prefix 'bin'
$dest = Join-Path $bin 'gum.exe'

# Prefer existing gum on PATH
$existing = Get-Command gum -ErrorAction SilentlyContinue
if ($existing) {
  Say "already on PATH: $($existing.Source)"
  exit 0
}
if ((Test-Path $dest)) {
  Say "already installed: $dest (add $bin to user PATH if needed)"
  exit 0
}

$arch = if ([Environment]::Is64BitOperatingSystem) { 'x86_64' } else { 'i386' }
$asset = "gum_${Version}_Windows_${arch}.zip"
$url = "https://github.com/charmbracelet/gum/releases/download/v${Version}/$asset"

if ($WhatIfPreference) {
  Say "[dry-run] would download $url"
  Say "[dry-run] would install gum.exe → $dest"
  exit 0
}

if (-not $Yes -and [Environment]::UserInteractive) {
  $ans = Read-Host "install-gum: gum (Charm) missing; download $asset into $dest now? [Y/n]"
  if ($ans -match '^(n|no)$') { Say 'skipped (legacy: familia.cmd -LegacyMenu)'; exit 1 }
}

if (-not (Test-Path $bin)) { New-Item -ItemType Directory -Force $bin | Out-Null }
$tmp = Join-Path ([IO.Path]::GetTempPath()) ('grz.' + [guid]::NewGuid().ToString('n'))
New-Item -ItemType Directory -Force $tmp | Out-Null
try {
  $zip = Join-Path $tmp $asset
  Say "downloading $url"
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
  Expand-Archive -Path $zip -DestinationPath $tmp -Force
  $gum = Get-ChildItem -Path $tmp -Recurse -Filter 'gum.exe' | Select-Object -First 1
  if (-not $gum) { throw "no gum.exe inside $asset" }
  Copy-Item -Force $gum.FullName $dest
  Say "installed $dest"
} catch {
  Say "error: $($_.Exception.Message)"
  Say 'retry later, or: winget install charmbracelet.gum / scoop install gum'
  Say 'legacy menu: familia.cmd -LegacyMenu'
  exit 1
} finally {
  Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

# Ensure bin is on user PATH (same store as install-cli.ps1)
$userPath = [string](Get-Item 'HKCU:\Environment').GetValue('Path', '', 'DoNotExpandEnvironmentNames')
$parts = @($userPath -split ';' | Where-Object { $_ })
if (-not ($parts | Where-Object { $_.TrimEnd('\') -ieq $bin.TrimEnd('\') })) {
  $newPath = if ($userPath) { "$bin;$userPath" } else { $bin }
  New-ItemProperty -Path 'HKCU:\Environment' -Name Path -Value $newPath -PropertyType ExpandString -Force | Out-Null
  $env:Path = "$bin;$env:Path"
  Say "added $bin to user PATH (new consoles pick it up)"
} else {
  Say "$bin already on user PATH"
}
exit 0
