$ErrorActionPreference = "Continue"
$env:PATH = "E:\temp\tools\mingw64\bin;" + $env:PATH
$root = "E:\temp\gpu-legacy"
$outDir = Join-Path $root "bench-concurrency"
New-Item -ItemType Directory -Force $outDir | Out-Null
$gpuExe = Join-Path $root "out\run_sm11.exe"
$cpuExe = "E:\temp\llama-cpu\llama-bench.exe"
$modelGpu = Join-Path $root "stories15M.bin"
$modelCpu = "E:\temp\llama-cpu\stories15M-q4_0.gguf"
$env:SM11_PTX = Join-Path $root "kernels.ptx"

function Start-Pinned([int]$mask, [string]$file, [string]$arguments, [string]$wd, [string]$stdout, [string]$stderr) {
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $file
  $psi.Arguments = $arguments
  $psi.WorkingDirectory = $wd
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.CreateNoWindow = $true
  $p = New-Object System.Diagnostics.Process
  $p.StartInfo = $psi
  [void]$p.Start()
  try { $p.ProcessorAffinity = [IntPtr]$mask } catch { "affinity: $_" | Out-File $stderr -Append }
  $stdoutJob = $p.StandardOutput.ReadToEndAsync()
  $stderrJob = $p.StandardError.ReadToEndAsync()
  $p.WaitForExit()
  [System.IO.File]::WriteAllText($stdout, $stdoutJob.Result)
  [System.IO.File]::WriteAllText($stderr, $stderrJob.Result)
  return $p
}
function Grab-CpuTps($paths) {
  $m = Select-String -Path $paths -Pattern 'tg256' -EA 0 | Select-Object -Last 1
  if (-not $m) { return $null }
  if ($m.Line -match 'tg256\s*\|\s*([0-9]+\.[0-9]+)') { return [double]$Matches[1] }
  return $null
}
function Grab-GpuTps($paths) {
  $m = Select-String -Path $paths -Pattern 'tok/s' -EA 0 | Select-Object -Last 1
  if (-not $m) { return $null }
  if ($m.Line -match 'tok/s:\s*([0-9.]+)') { return [double]$Matches[1] }
  return $null
}

$gpuArgs = "`"$modelGpu`" -t 0 -n 256 -i `"Once upon a time`""
$cpuArgs = "-m `"$modelCpu`" -t 1 -p 64 -n 256 -r 3"

"=== A: GPU alone (CPU1) ==="
$env:FAMILIA_GPU = "1"; $env:OMP_NUM_THREADS = "1"
$sw = [Diagnostics.Stopwatch]::StartNew()
[void](Start-Pinned 2 $gpuExe $gpuArgs $root "$outDir\gpu-alone.txt" "$outDir\gpu-alone.err")
$sw.Stop()
"GPU alone wall_s=$([math]::Round($sw.Elapsed.TotalSeconds,2))"
Get-Content "$outDir\gpu-alone.err","$outDir\gpu-alone.txt" -EA 0 | Select-String "tok/s|backend|resident|error|PTX|Usage"

"=== B: CPU alone Q4_0 (CPU0, t=1) ==="
$env:FAMILIA_GPU = "0"
$sw.Restart()
[void](Start-Pinned 1 $cpuExe $cpuArgs "E:\temp\llama-cpu" "$outDir\cpu-alone.txt" "$outDir\cpu-alone.err")
$sw.Stop()
"CPU alone wall_s=$([math]::Round($sw.Elapsed.TotalSeconds,2))"
Get-Content "$outDir\cpu-alone.txt","$outDir\cpu-alone.err" -EA 0 | Select-String "tg256"

"=== C: BOTH (CPU0=bench, CPU1=GPU) ==="
$env:FAMILIA_GPU = "1"; $env:OMP_NUM_THREADS = "1"
# start both concurrently with ProcessStartInfo
$psiC = New-Object System.Diagnostics.ProcessStartInfo
$psiC.FileName = $cpuExe; $psiC.Arguments = $cpuArgs; $psiC.WorkingDirectory = "E:\temp\llama-cpu"
$psiC.UseShellExecute = $false; $psiC.RedirectStandardOutput = $true; $psiC.RedirectStandardError = $true; $psiC.CreateNoWindow = $true
$psiG = New-Object System.Diagnostics.ProcessStartInfo
$psiG.FileName = $gpuExe; $psiG.Arguments = $gpuArgs; $psiG.WorkingDirectory = $root
$psiG.UseShellExecute = $false; $psiG.RedirectStandardOutput = $true; $psiG.RedirectStandardError = $true; $psiG.CreateNoWindow = $true
$psiG.EnvironmentVariables["FAMILIA_GPU"] = "1"
$psiG.EnvironmentVariables["OMP_NUM_THREADS"] = "1"
$psiG.EnvironmentVariables["SM11_PTX"] = $env:SM11_PTX
$psiG.EnvironmentVariables["PATH"] = $env:PATH
$sw.Restart()
$pc = New-Object System.Diagnostics.Process; $pc.StartInfo = $psiC; [void]$pc.Start()
try { $pc.ProcessorAffinity = [IntPtr]1 } catch {}
Start-Sleep -Milliseconds 400
$pg = New-Object System.Diagnostics.Process; $pg.StartInfo = $psiG; [void]$pg.Start()
try { $pg.ProcessorAffinity = [IntPtr]2 } catch {}
$cout = $pc.StandardOutput.ReadToEndAsync(); $cerr = $pc.StandardError.ReadToEndAsync()
$gout = $pg.StandardOutput.ReadToEndAsync(); $gerr = $pg.StandardError.ReadToEndAsync()
$pc.WaitForExit(); $pg.WaitForExit(); $sw.Stop()
[System.IO.File]::WriteAllText("$outDir\cpu-both.txt", $cout.Result)
[System.IO.File]::WriteAllText("$outDir\cpu-both.err", $cerr.Result)
[System.IO.File]::WriteAllText("$outDir\gpu-both.txt", $gout.Result)
[System.IO.File]::WriteAllText("$outDir\gpu-both.err", $gerr.Result)
"BOTH wall_s=$([math]::Round($sw.Elapsed.TotalSeconds,2))"
"CPU both:"; Get-Content "$outDir\cpu-both.txt","$outDir\cpu-both.err" -EA 0 | Select-String "tg256"
"GPU both:"; Get-Content "$outDir\gpu-both.err","$outDir\gpu-both.txt" -EA 0 | Select-String "tok/s|backend|Usage"

$cpuA = Grab-CpuTps @("$outDir\cpu-alone.txt","$outDir\cpu-alone.err")
$gpuA = Grab-GpuTps @("$outDir\gpu-alone.err","$outDir\gpu-alone.txt")
$cpuB = Grab-CpuTps @("$outDir\cpu-both.txt","$outDir\cpu-both.err")
$gpuB = Grab-GpuTps @("$outDir\gpu-both.err","$outDir\gpu-both.txt")
if ($null -eq $cpuA) { $cpuA = 0 }; if ($null -eq $gpuA) { $gpuA = 0 }
if ($null -eq $cpuB) { $cpuB = 0 }; if ($null -eq $gpuB) { $gpuB = 0 }
$dCpu = if ($cpuA -gt 0) { [math]::Round(100*($cpuB-$cpuA)/$cpuA,1) } else { "n/a" }
$dGpu = if ($gpuA -gt 0) { [math]::Round(100*($gpuB-$gpuA)/$gpuA,1) } else { "n/a" }
$sum = @"
# Concurrency bench - qodesh Athlon II X2 (2 threads), pinned

| run | CPU Q4_0 tg256 (t/s) | GPU stories15M (t/s) | combined |
|---|---:|---:|---:|
| alone | $cpuA | $gpuA | $($cpuA + $gpuA) |
| concurrent (CPU0+CPU1) | $cpuB | $gpuB | $($cpuB + $gpuB) |

Delta CPU: $dCpu%
Delta GPU: $dGpu%
Net: combined_both=$($cpuB+$gpuB) vs max(alone)=$([math]::Max($cpuA,$gpuA)) vs sum(alone)=$($cpuA+$gpuA)
Pinning: CPU llama-bench affinity=CPU0 (mask 1), GPU run_sm11 affinity=CPU1 (mask 2).
"@
$sum | Set-Content "$outDir\SUMMARY.md" -Encoding utf8
$sum
