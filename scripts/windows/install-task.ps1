<#
.SYNOPSIS
  OPT-IN: register a per-user Scheduled Task that runs scripts\windows\start.bat at logon (#17).
.DESCRIPTION
  Does nothing unless -Install is given. -Uninstall removes the task. -WhatIf shows what would happen.
  Runs as the current user, only when logged on, no elevation, no stored password.
  Environment for start.bat is passed through -Model/-ModelsPath/-Port etc. and written into
  the task's command line, so the user's global environment is not modified.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\install-task.ps1 -Install -Model qwen2.5-0.5b-instruct-q4_0.gguf
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\install-task.ps1 -Uninstall
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [switch]$Install,
  [switch]$Uninstall,
  [string]$TaskName = 'familia-llama-server',
  [string]$Model,
  [string]$ModelsPath,
  [string]$RuntimePath,
  [int]$Port = 9941,
  [int]$Ctx = 4096,
  [int]$Threads = 2,
  [int]$DelaySeconds = 60
)
$ErrorActionPreference = 'Stop'
$bat = Join-Path $PSScriptRoot 'start.bat'
if (-not (Test-Path $bat)) { throw "start.bat not found next to this script: $bat" }

if ($Uninstall) {
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister scheduled task')) {
      Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
      Write-Host "familia: removed task $TaskName"
    }
  } else { Write-Host "familia: no task named $TaskName" }
  return
}
if (-not $Install) {
  Write-Host 'familia: autostart is opt-in. Re-run with -Install (and -Model) to register the logon task, or -Uninstall to remove it.'
  return
}
if (-not $Model) { throw 'Give -Model (GGUF file name in the models dir, or a full path).' }

$envs = @("FAMILIA_MODEL=$Model", "FAMILIA_PORT=$Port", "FAMILIA_CTX=$Ctx", "FAMILIA_THREADS=$Threads")
if ($ModelsPath)  { $envs += "FAMILIA_MODELS=$ModelsPath" }
if ($RuntimePath) { $envs += "FAMILIA_RUNTIME=$RuntimePath" }
$sets = ($envs | ForEach-Object { "set `"$_`"" }) -join ' && '
$arg  = "/c $sets && `"$bat`""

$action    = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument $arg -WorkingDirectory (Split-Path $bat)
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$trigger.Delay = "PT${DelaySeconds}S"   # let Windows settle; qodesh is a slow 2-core box
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
               -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
if ($PSCmdlet.ShouldProcess($TaskName, "Register logon task running $bat")) {
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'familia: start llama-server at logon (opt-in, #17)' -Force | Out-Null
  Write-Host "familia: registered $TaskName (runs at logon after ${DelaySeconds}s). Remove with -Uninstall."
}
