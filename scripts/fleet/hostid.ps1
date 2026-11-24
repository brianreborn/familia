# familia fleet host ID for Windows (same algorithm as scripts/fleet/hostid.sh / hostid.py).
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\fleet\hostid.ps1 [-Label NAME] [-Json]
# Anchor: HKLM\SOFTWARE\Microsoft\Cryptography MachineGuid (machine-guid); fallback
# %LOCALAPPDATA%\familia\host-uuid (state-uuid); else weak hostname ID. Read-only; the
# raw anchor is never printed, only sha256("familia-hostid-v1|<type>|<anchor>")[:8].
param([string]$Label = "", [switch]$Json)
$ErrorActionPreference = "SilentlyContinue"
$type = ""; $val = ""
$g = (Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Cryptography" -Name MachineGuid).MachineGuid
if ($g) { $type = "machine-guid"; $val = $g }
$sd = Join-Path $env:LOCALAPPDATA "familia"
if (-not $type -and (Test-Path (Join-Path $sd "host-uuid"))) { $type = "state-uuid"; $val = (Get-Content (Join-Path $sd "host-uuid") -TotalCount 1) }
if (-not $Label) { $Label = $env:FAMILIA_HOST_LABEL }
if (-not $Label -and (Test-Path (Join-Path $sd "hostname"))) { $Label = (Get-Content (Join-Path $sd "hostname") -TotalCount 1) }
if (-not $Label) { $Label = $env:COMPUTERNAME }
$slug = ($Label.Split(".")[0].ToLower() -replace "[^a-z0-9-]", "-" -replace "-+", "-").Trim("-")
if ($slug.Length -gt 24) { $slug = $slug.Substring(0, 24).Trim("-") }
if (-not $slug -or $slug -eq "localhost") { $slug = "host" }
$val = ($val -replace "\s", "").ToLower()
if (-not $type -or -not $val) { $type = "hostname"; $val = $slug }
$sha = [System.Security.Cryptography.SHA256]::Create()
$bytes = $sha.ComputeHash([System.Text.Encoding]::ASCII.GetBytes("familia-hostid-v1|$type|$val"))
$fp = (($bytes | ForEach-Object { $_.ToString("x2") }) -join "").Substring(0, 8)
$val = ""
if ($Json) {
  $weak = if ($type -eq "hostname") { "true" } else { "false" }
  Write-Output ('{"host_id": "' + "$slug-$fp" + '", "label": "' + $slug + '", "fingerprint": "' + $fp + '", "anchor_type": "' + $type + '", "weak": ' + $weak + '}')
} else { Write-Output "$slug-$fp" }
