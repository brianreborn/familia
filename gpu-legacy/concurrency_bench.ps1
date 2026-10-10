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

function Start-Proc([string]$file, [string]$arguments, [string]$wd, [hashtable]$extraEnv, [int]$affinity) {
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $file; $psi.Arguments = $arguments; $psi.WorkingDirectory = $wd
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
  foreach ($k in @('PATH','SM11_PTX','FAMILIA_GPU','OMP_NUM_THREADS','SM11_FULL_FWD','SM11_PARTIAL','SM11_GPU_CLS','SM11_RESIDENT_MIB')) {
    $v = [Environment]::GetEnvironmentVariable($k)
    if ($v) { $psi.EnvironmentVariables[$k] = $v }
  }
  $psi.EnvironmentVariables['PATH'] = $env:PATH
  $psi.EnvironmentVariables['SM11_PTX'] = $env:SM11_PTX
  if ($extraEnv) { foreach ($k in $extraEnv.Keys) { $psi.EnvironmentVariables[$k] = [string]$extraEnv[$k] } }
  $p = New-Object System.Diagnostics.Process; $p.StartInfo = $psi; [void]$p.Start()
  if ($affinity -gt 0) { try { $p.ProcessorAffinity = [IntPtr]$affinity } catch {} }
  return $p
}
function Grab-CpuTps($paths) {
  $m = Select-String -Path $paths -Pattern 'tg256' -EA 0 | Select-Object -Last 1
  if ($m -and $m.Line -match 'tg256\s*\|\s*([0-9]+\.[0-9]+)') { return [double]$Matches[1] }
  return 0
}
function Grab-GpuTps($paths) {
  $m = Select-String -Path $paths -Pattern 'tok/s:\s*([0-9.]+)' -EA 0 | Select-Object -Last 1
  if ($m) { return [double]$Matches[1] }
  return 0
}
function Grab-Resident($paths) {
  $m = Select-String -Path $paths -Pattern 'resident\s+(\d+)\s+MiB\s+/\s+(\d+)' -EA 0 | Select-Object -Last 1
  if ($m) { return "$($Matches[1])/$($Matches[2])" }
  return "?"
}

$gpuArgs = "`"$modelGpu`" -t 0 -n 256 -i `"Once upon a time`""
$cpuArgs = "-m `"$modelCpu`" -t 1 -p 64 -n 256 -r 3"
# Fast path: full forward, CPU classifier with both OpenMP threads, do NOT pin GPU to 1 core
$gpuEnv = @{ FAMILIA_GPU = "1"; OMP_NUM_THREADS = "2"; SM11_FULL_FWD = "1"; SM11_PARTIAL = "0"; SM11_GPU_CLS = "0" }

"=== A: GPU alone fast-path (unpinned, OMP=2, full-fwd) ==="
$sw = [Diagnostics.Stopwatch]::StartNew()
$pg = Start-Proc $gpuExe $gpuArgs $root $gpuEnv 0
$gout = $pg.StandardOutput.ReadToEndAsync(); $gerr = $pg.StandardError.ReadToEndAsync()
$pg.WaitForExit(); $sw.Stop()
[IO.File]::WriteAllText("$outDir\gpu-alone.txt", $gout.Result)
[IO.File]::WriteAllText("$outDir\gpu-alone.err", $gerr.Result)
"GPU alone wall_s=$([math]::Round($sw.Elapsed.TotalSeconds,2)) resident=$(Grab-Resident @("$outDir\gpu-alone.err")) tok/s=$(Grab-GpuTps @("$outDir\gpu-alone.err"))"

"=== B: CPU alone Q4_0 (pinned CPU0, t=1) ==="
$sw.Restart()
$pc = Start-Proc $cpuExe $cpuArgs "E:\temp\llama-cpu" @{ OMP_NUM_THREADS = "1"; FAMILIA_GPU = "0" } 1
$cout = $pc.StandardOutput.ReadToEndAsync(); $cerr = $pc.StandardError.ReadToEndAsync()
$pc.WaitForExit(); $sw.Stop()
[IO.File]::WriteAllText("$outDir\cpu-alone.txt", $cout.Result)
[IO.File]::WriteAllText("$outDir\cpu-alone.err", $cerr.Result)
"CPU alone wall_s=$([math]::Round($sw.Elapsed.TotalSeconds,2)) tok/s=$(Grab-CpuTps @("$outDir\cpu-alone.txt","$outDir\cpu-alone.err"))"

"=== C: BOTH — CPU pinned CPU0; GPU unpinned OMP=2 full-fwd ==="
$sw.Restart()
$pc = Start-Proc $cpuExe $cpuArgs "E:\temp\llama-cpu" @{ OMP_NUM_THREADS = "1"; FAMILIA_GPU = "0" } 1
Start-Sleep -Milliseconds 300
$pg = Start-Proc $gpuExe $gpuArgs $root $gpuEnv 0
$cout = $pc.StandardOutput.ReadToEndAsync(); $cerr = $pc.StandardError.ReadToEndAsync()
$gout = $pg.StandardOutput.ReadToEndAsync(); $gerr = $pg.StandardError.ReadToEndAsync()
$pc.WaitForExit(); $pg.WaitForExit(); $sw.Stop()
[IO.File]::WriteAllText("$outDir\cpu-both.txt", $cout.Result); [IO.File]::WriteAllText("$outDir\cpu-both.err", $cerr.Result)
[IO.File]::WriteAllText("$outDir\gpu-both.txt", $gout.Result); [IO.File]::WriteAllText("$outDir\gpu-both.err", $gerr.Result)
"BOTH wall_s=$([math]::Round($sw.Elapsed.TotalSeconds,2))"
"CPU both=$(Grab-CpuTps @("$outDir\cpu-both.txt","$outDir\cpu-both.err")) GPU both=$(Grab-GpuTps @("$outDir\gpu-both.err")) resident=$(Grab-Resident @("$outDir\gpu-both.err"))"

$cpuA = Grab-CpuTps @("$outDir\cpu-alone.txt","$outDir\cpu-alone.err")
$gpuA = Grab-GpuTps @("$outDir\gpu-alone.err")
$cpuB = Grab-CpuTps @("$outDir\cpu-both.txt","$outDir\cpu-both.err")
$gpuB = Grab-GpuTps @("$outDir\gpu-both.err")
$resA = Grab-Resident @("$outDir\gpu-alone.err")
$resB = Grab-Resident @("$outDir\gpu-both.err")
$dCpu = if ($cpuA -gt 0) { [math]::Round(100*($cpuB-$cpuA)/$cpuA,1) } else { "n/a" }
$dGpu = if ($gpuA -gt 0) { [math]::Round(100*($gpuB-$gpuA)/$gpuA,1) } else { "n/a" }
@"
# Concurrency bench — qodesh Athlon II X2 (fast path)

Root cause of prior 17 t/s: GPU process pinned to 1 core with OMP_NUM_THREADS=1 **and** VRAM budget left only ~4/57 MiB resident (host-streaming matvecs). Fast path = full ``sm11_forward``, full weight residency, OMP=2 for CPU classifier, GPU process **unpinned**.

| run | CPU Q4_0 tg256 (t/s) | GPU stories15M (t/s) | GPU resident MiB | combined |
|---|---:|---:|---|---:|
| alone | $cpuA | $gpuA | $resA | $($cpuA+$gpuA) |
| concurrent | $cpuB | $gpuB | $resB | $($cpuB+$gpuB) |

Delta CPU: $dCpu%
Delta GPU: $dGpu%
Pinning: llama-bench affinity=CPU0; GPU run_sm11 unpinned OMP=2 SM11_FULL_FWD=1.
"@ | Tee-Object "$outDir\SUMMARY.md"
