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

# Charm's published checksums.txt for gum v2.0.2. A version override cannot skip this.
$PinnedVersion = '2.0.2'
$PinnedSha = @{
  'gum_2.0.2_Windows_x86_64.zip' = '0397091dec9b4e8f00e02b90fd3eb07bf45acabbdb61d67437950f18e03a8b79'
  'gum_2.0.2_Windows_i386.zip'    = '0c2c172568c9ae6d059ca7fe3ef08fc9f5b2842cbbf813c33dfd1985aba01037'
}
if ($Version -ne $PinnedVersion) {
  Say "FAMILIA_GUM_VERSION=$Version is not pinned $PinnedVersion; refusing to skip checksum verification"
  exit 1
}
$arch = if ([Environment]::Is64BitOperatingSystem) { 'x86_64' } else { 'i386' }
$asset = "gum_${Version}_Windows_${arch}.zip"
$url = "https://github.com/charmbracelet/gum/releases/download/v${Version}/$asset"
if (-not $url.StartsWith('https://')) { Say "refusing non-https URL: $url"; exit 1 }
$wantSha = $PinnedSha[$asset]
if (-not $wantSha) { Say "no pinned sha256 for $asset"; exit 1 }

if ($WhatIfPreference) {
  Say "[dry-run] would download $url"
  Say "[dry-run] would install gum.exe → $dest"
  exit 0
}

if (-not $Yes) {
  if (-not [Environment]::UserInteractive) {
    Say 'not a terminal and -Yes was not given; not downloading gum'
    exit 1
  }
  $ans = Read-Host "install-gum: gum (Charm) missing; download $asset into $dest now? [y/N]"
  if ($ans -notmatch '^(y|yes)$') { Say 'skipped (legacy: familia.cmd -LegacyMenu)'; exit 1 }
}

if (-not (Test-Path $bin)) { New-Item -ItemType Directory -Force $bin | Out-Null }
$tmp = Join-Path ([IO.Path]::GetTempPath()) ('grz.' + [guid]::NewGuid().ToString('n'))
New-Item -ItemType Directory $tmp | Out-Null
try {
  $zip = Join-Path $tmp $asset
  Say "downloading $url"
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
  $got = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLowerInvariant()
  if ($got -ne $wantSha) { throw "sha256 mismatch for $asset (got $got, want $wantSha)" }
  Say 'sha256 ok'
  Expand-Archive -Path $zip -DestinationPath $tmp -Force
  $gum = Get-ChildItem -Path $tmp -Recurse -Filter 'gum.exe' | Select-Object -First 1
  if (-not $gum) { throw "no gum.exe inside $asset" }
  $stage = "$dest.tmp.$PID"
  Copy-Item -Force $gum.FullName $stage
  Move-Item -Force $stage $dest
  Say "installed $dest"
} catch {
  Say "error: $($_.Exception.Message)"
  Say 'retry later, or: winget install charmbracelet.gum / scoop install gum'
  Say 'legacy menu: familia.cmd -LegacyMenu'
  exit 1
} finally {
  Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

# Session PATH only. A permanent edit is a separate question, default no, and -Yes does not ask.
$env:Path = "$bin;$env:Path"
Say "this session can see $bin"
if (-not $Yes -and [Environment]::UserInteractive) {
  $keep = Read-Host "install-gum: add $bin to the user PATH permanently? [y/N]"
  if ($keep -match '^(y|yes)$') {
    $userPath = [string](Get-Item 'HKCU:\Environment').GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    $parts = @($userPath -split ';' | Where-Object { $_ })
    if (-not ($parts | Where-Object { $_.TrimEnd('\') -ieq $bin.TrimEnd('\') })) {
      $newPath = if ($userPath) { "$bin;$userPath" } else { $bin }
      New-ItemProperty -Path 'HKCU:\Environment' -Name Path -Value $newPath -PropertyType ExpandString -Force | Out-Null
      Say "added $bin to user PATH (new consoles pick it up)"
    } else {
      Say "$bin already on user PATH"
    }
  } else {
    Say 'left the user PATH unchanged'
  }
}
exit 0
