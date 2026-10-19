# familia monitor probe for Windows (PowerShell 5.1+). Read-only; prints one JSON object.
# Piped over SSH (no install on the remote, no $ on the command line so cmd.exe and Git bash agree):
#   ssh HOST 'powershell -NoProfile -NonInteractive -Command "[Console]::In.ReadToEnd() | Invoke-Expression"' < probe.ps1
# Ports to health-check come from $env:FAMILIA_PROBE_PORTS or the first line the console prepends:
#   $FamiliaPorts = @(18100,18101)
$ErrorActionPreference = 'SilentlyContinue'
$t0 = Get-Date
if (-not $FamiliaPorts) { $FamiliaPorts = @() }
if ($env:FAMILIA_PROBE_PORTS) { $FamiliaPorts += ($env:FAMILIA_PROBE_PORTS -split ',' | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ }) }
if (-not $FamiliaSince) { $FamiliaSince = (Get-Date).AddHours(-1) } else { $FamiliaSince = ([DateTime]'1970-01-01Z').AddSeconds($FamiliaSince).ToLocalTime() }
function Redact([string]$s) {
  if (-not $s) { return $s }
  $s = $s -replace '(hf_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,})', '***'
  return ($s -replace '(?i)(--api-key(-file)?|--hf-token|-hft)(\s+|=)\S+', '$1 ***')
}
function Epoch($d) { if ($d) { return [int64](($d.ToUniversalTime() - [DateTime]'1970-01-01').TotalSeconds) } else { return $null } }
$os = Get-CimInstance Win32_OperatingSystem
$now = Get-Date
$boot = $os.LastBootUpTime
$cpuCores = @{}
Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor | ForEach-Object {
  $k = if ($_.Name -eq '_Total') { 'cpu' } else { 'cpu' + $_.Name }
  $cpuCores[$k] = [double]$_.PercentProcessorTime
}
$pf = Get-CimInstance Win32_PageFileUsage
$mem = [ordered]@{
  total_mib = [int]($os.TotalVisibleMemorySize / 1024); available_mib = [int]($os.FreePhysicalMemory / 1024)
  swap_total_mib = [int](($pf | Measure-Object AllocatedBaseSize -Sum).Sum); swap_free_mib = [int](($pf | Measure-Object AllocatedBaseSize -Sum).Sum - ($pf | Measure-Object CurrentUsage -Sum).Sum)
  commit_limit_mib = [int]($os.TotalVirtualMemorySize / 1024); commit_free_mib = [int]($os.FreeVirtualMemory / 1024)
}
$procs = Get-Process
$top = $procs | Sort-Object WorkingSet64 -Descending | Select-Object -First 8 | ForEach-Object {
  [ordered]@{ pid = $_.Id; comm = $_.ProcessName; rss_mib = [int]($_.WorkingSet64 / 1MB); cpu_s = [math]::Round($_.CPU, 1) }
}
$fam = @()
Get-CimInstance Win32_Process -Filter "Name LIKE 'llama%' OR Name LIKE 'rpc-server%' OR Name LIKE 'python%' OR Name LIKE 'hermes%'" | ForEach-Object {
  $cl = [string]$_.CommandLine
  $name = $_.Name -replace '\.exe$', ''
  $kind = $null
  if ($name -match '^(llama-server|llama-cli|llama-bench|rpc-server|llama-embedding)$') { $kind = $name }
  elseif ($cl -match '(hermes_harness\.py|escalation_proxy\.py|escalate\.py|\bhermes\b)') { $kind = $Matches[1] }
  if ($kind) {
    $f = [ordered]@{}
    $map = @{ '-m'='model'; '--model'='model'; '-c'='ctx'; '--ctx-size'='ctx'; '-ngl'='ngl'; '--n-gpu-layers'='ngl'; '-t'='threads'; '--threads'='threads'; '--port'='port'; '--host'='bind'; '-np'='parallel'; '--parallel'='parallel'; '-ctk'='kv_type'; '--cache-type-k'='kv_type'; '--cache-ram'='cache_ram'; '-a'='alias'; '--alias'='alias' }
    $tok = @([regex]::Matches($cl, '"[^"]*"|\S+') | ForEach-Object { $_.Value.Trim('"') })
    for ($i = 0; $i -lt $tok.Count - 1; $i++) { if ($map.ContainsKey($tok[$i])) { $v = $tok[$i + 1]; if ($map[$tok[$i]] -eq 'model') { $v = Split-Path $v -Leaf }; $f[$map[$tok[$i]]] = $v } }
    if ($kind -eq 'llama-server' -and -not $f.Contains('port')) { $f['port'] = '8080' }
    $gp = Get-Process -Id $_.ProcessId
    $fam += [ordered]@{ pid = [int]$_.ProcessId; kind = $kind; start = (Epoch $_.CreationDate); state = 'R'
      rss_mib = [int]($_.WorkingSetSize / 1MB); cpu_s = [math]::Round($gp.CPU, 1)
      uptime_s = [int]($now - $_.CreationDate).TotalSeconds; flags = $f; cmd = (Redact $cl).Substring(0, [math]::Min(300, (Redact $cl).Length)) }
  }
}
$health = @()
foreach ($port in ($FamiliaPorts | Select-Object -Unique | Select-Object -First 32)) {
  $r = [ordered]@{ port = $port }
  foreach ($pair in @(@('/health','health'), @('/v1/models','models'))) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
      $req = [Net.WebRequest]::Create("http://127.0.0.1:$port$($pair[0])"); $req.Timeout = 600
      $resp = $req.GetResponse(); $r[$pair[1]] = [int]$resp.StatusCode; $resp.Close()
    } catch [Net.WebException] {
      if ($_.Exception.Response) { $r[$pair[1]] = [int]$_.Exception.Response.StatusCode } else { $r[$pair[1]] = 'down'; $r['ms'] = $sw.ElapsedMilliseconds; break }
    }
    $r['ms'] = $sw.ElapsedMilliseconds
  }
  $health += $r
}
$gpus = @()
$smi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source
if (-not $smi -and (Test-Path 'C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe')) { $smi = 'C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe' }
if ($smi) {
  # The legacy 340.xx driver (8600 GT) answers N/A for most GeForce fields; keep what it gives.
  & $smi --query-gpu=name,driver_version,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>$null | ForEach-Object {
    $x = $_ -split ',\s*'; if ($x.Count -ge 6) { $gpus += [ordered]@{ source='nvidia-smi'; name=$x[0]; driver=$x[1]; temp_c=$x[2]; util_pct=$x[3]; mem_used_mib=$x[4]; mem_total_mib=$x[5] } }
  }
}
Get-CimInstance Win32_VideoController | ForEach-Object {
  $gpus += [ordered]@{ source = 'wmi'; name = $_.Name; driver = $_.DriverVersion; vram_mib = [int]($_.AdapterRAM / 1MB); status = $_.Status }
}
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object { [ordered]@{ mount = $_.DeviceID; free_mib = [int64]($_.FreeSpace / 1MB); total_mib = [int64]($_.Size / 1MB) } })
$temps = @(Get-CimInstance -Namespace root/wmi MSAcpi_ThermalZoneTemperature | ForEach-Object { [ordered]@{ name = 'acpi'; c = [math]::Round($_.CurrentTemperature / 10 - 273.15, 1) } })
$kills = @(Get-WinEvent -FilterHashtable @{ LogName = 'System'; ProviderName = 'Microsoft-Windows-Resource-Exhaustion-Detector'; StartTime = $FamiliaSince } -MaxEvents 5 | ForEach-Object {
  [ordered]@{ ts = (Epoch $_.TimeCreated); source = 'resource-exhaustion'; pid = $null; name = (Redact ($_.Message -split "`n")[0]) } })
$logs = [ordered]@{}
$cands = @("$env:USERPROFILE\familia-perf.log", "$env:USERPROFILE\.cache\familia\logs\*.log", 'E:\temp\familia\*.log', "$env:USERPROFILE\familia\.cache\familia\*.log", 'E:\temp\familia\.cache\familia\*.log')
Get-ChildItem $cands -File | Sort-Object LastWriteTime -Descending | Select-Object -First 6 | ForEach-Object {
  $logs[$_.FullName] = [ordered]@{ mtime = (Epoch $_.LastWriteTime); tail = @(Get-Content $_.FullName -Tail 4 | ForEach-Object { (Redact $_).Substring(0, [math]::Min(200, (Redact $_).Length)) }) }
}
$me = Get-Process -Id $PID
$res = [ordered]@{
  v = 1; ok = $true; platform = 'windows'; hostname = $env:COMPUTERNAME; time = (Epoch $now); boot_time = (Epoch $boot)
  uptime_s = [int]($now - $boot).TotalSeconds; load = @(); ncpu = [int]$env:NUMBER_OF_PROCESSORS; cpu_pct = $cpuCores
  mem = $mem; top = @($top); familia = @($fam); health = @($health); kills = $kills; logs = $logs
  os = "$($os.Caption) $($os.Version)"; disks = $disks; temps = $temps; gpus = @($gpus); battery = $null; zram = @(); swaps = @()
  probe = [ordered]@{ elapsed_ms = [int]((Get-Date) - $t0).TotalMilliseconds; cpu_ms = [int]($me.CPU * 1000); maxrss_kib = [int]($me.PeakWorkingSet64 / 1KB); pid = $PID }
}
$res | ConvertTo-Json -Depth 6 -Compress
