<#
.SYNOPSIS
  Background free-download of first-try CPU models (protomodel / safe-build).
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\prefetch-first-models.ps1 -Background
#>
[CmdletBinding()]
param(
  [switch]$Background,
  [switch]$DryRun,
  [switch]$Status
)
$ErrorActionPreference = 'Continue'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$cache = Join-Path $root '.cache'
$log = Join-Path $cache 'prefetch-first-models.log'
$pidf = Join-Path $cache 'prefetch-first-models.pid'
function Say([string]$m) { Write-Host "prefetch: $m" }
if (-not (Test-Path $cache)) { New-Item -ItemType Directory -Force $cache | Out-Null }

if ($Status) {
  if ((Test-Path $pidf)) {
    $p = Get-Content $pidf -ErrorAction SilentlyContinue
    Say "last-pid=$p log=$log"
  } else { Say "IDLE log=$log" }
  if (Test-Path $log) { Get-Content $log -Tail 3 | ForEach-Object { Write-Host "  $_" } }
  exit 0
}

$sh = Join-Path $root 'scripts\prefetch-first-models.sh'
# Prefer bash when present (Git Bash / WSL); else call python add_model directly via the sh logic with bash -lc
$bash = Get-Command bash -ErrorAction SilentlyContinue
if ($Background) {
  if ($DryRun) { Say "[dry-run] would Start-Job → $log"; exit 0 }
  Say "background → $log"
  $job = Start-Job -ScriptBlock {
    param($root, $log, $pidf, $bashPath, $sh)
    Set-Content -Path $pidf -Value $PID
    try {
      if ($bashPath) {
        & $bashPath $sh *>> $log
      } else {
        # Inline fallback without bash: two add_model fetches
        $py = Get-Command python -ErrorAction SilentlyContinue
        if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
        if (-not $py) { Add-Content $log 'prefetch: no python; skip'; return }
        $env:FAMILIA_ACCEPT_LICENSES = 'yes'
        $models = @(
          @{ Spec = 'bartowski/SmolLM2-135M-Instruct-GGUF@09816acd5d99df7be770d85ea30822623dab342c'; File = 'SmolLM2-135M-Instruct-Q4_0.gguf'; Role = 'chat' },
          @{ Spec = 'ggml-org/Laya-GGUF@da4b4753d62197659d8c90103cd4c43bef9afea6'; File = 'Laya-Q8_0.gguf'; Role = 'decision' }
        )
        foreach ($m in $models) {
          Add-Content $log "prefetch: ORDNANCE $($m.Spec)"
          & $py.Source (Join-Path $root 'scripts\add_model.py') --fetch $m.Spec --file $m.File --role $m.Role --yes *>> $log
        }
        Add-Content $log "prefetch: done"
      }
    } finally {
      Remove-Item $pidf -ErrorAction SilentlyContinue
    }
  } -ArgumentList $root, $log, $pidf, $(if ($bash) { $bash.Source } else { $null }), $sh
  Say "Start-Job id=$($job.Id) log=$log"
  exit 0
}

if ($DryRun) {
  if ($bash) { & $bash.Source $sh --dry-run } else { Say '[dry-run] would fetch SmolLM2-135M Q4_0 + Laya-Q8_0 via add_model.py' }
  exit 0
}
if ($bash) { & $bash.Source $sh } else {
  Say 'no bash; use -Background (python fallback) or install Git Bash'
  exit 1
}
