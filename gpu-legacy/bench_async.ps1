$env:PATH = "E:\temp\tools\mingw64\bin;" + $env:PATH   # libgomp for run_sm11 (OpenMP)
$ErrorActionPreference = "Continue"
$root = "E:\temp\gpu-legacy"; Set-Location $root
$log = Join-Path $root "progress.log"
function P($m){ "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $m" | Tee-Object -Append $log }
function T($lines){ $lines | Tee-Object -Append $log }
$M = "E:\temp\models\SmolLM2-135M-Instruct.Q4_0.gguf"; $B = "E:\temp\llama.cpp\build-sm11\bin"
$env:SM11_FULL_FWD = "1"; $env:OMP_NUM_THREADS = "2"; $env:SMOL_CTX = "64"
$res = [ordered]@{}
function Stories($exe, $tag, $extra) {
  $raw = & ".\out\$exe" stories15M.bin -t 0 -n 256 -i "Once upon a time" 2>&1
  $o = $raw | Out-String
  $stdout = ($raw | Where-Object { $_ -is [string] }) -join "`n"   # stderr lines are ErrorRecords: exclude (text-compare bug fix)
  $tps = [regex]::Match($o, 'achieved tok/s: ([0-9.]+)').Groups[1].Value
  $txt = ($stdout -split "`n" | Where-Object { $_ -notmatch 'achieved tok/s' }) -join "`n"
  "[$tag] stories15M tok/s=$tps" | Add-Content $log; Write-Host "stories15M [$tag] tok/s=$tps"; return @($tps, $txt.Trim())
}
P "MILESTONE: bench A - stories15M full-forward, before (blocking sync) vs after (async)"
$a = $null; $b = $null; $ra=@(); $rb=@()
for ($k = 0; $k -lt 3; $k++) { $a = Stories "run_sm11_v1sync.exe" "before-sync"; $ra += [double]$a[0]; $b = Stories "run_sm11.exe" "after-async"; $rb += [double]$b[0] }
T ("stories15M before runs: " + ($ra -join ', ') + " | after runs: " + ($rb -join ', '))
$res["stories_before_max"] = ($ra | Measure-Object -Maximum).Maximum; $res["stories_after_max"] = ($rb | Measure-Object -Maximum).Maximum
T "stories15M text identical before/after: $($a[1] -eq $b[1])"
$res["stories_text_equal"] = ($a[1] -eq $b[1])

P "MILESTONE: bench B - SmolLM2 full-forward, before (DtoH sync/token) vs after (async event poll)"
$ids = "504,3575,282,4649,314"
$o1 = (& .\out\smol_sm11_v1sync.exe $M $ids 48 gpu 2>$null) -join "`n"; T ($o1 -split "`n" | Select-String 'tps|ids')
$o2 = (& .\out\smol_sm11.exe $M $ids 48 gpu 2>$null) -join "`n"; T ($o2 -split "`n" | Select-String 'tps|ids')
$res["smol_before"] = [regex]::Match($o1,'gpu_tps=([0-9.]+)').Groups[1].Value
$res["smol_after"] = [regex]::Match($o2,'gpu_tps=([0-9.]+)').Groups[1].Value
$res["smol_ids_equal_before_after"] = ([regex]::Match($o1,'gpu_ids=([0-9,]+)').Value -eq [regex]::Match($o2,'gpu_ids=([0-9,]+)').Value)

P "MILESTONE: verify - SmolLM2 GPU vs CPU reference (3 prompts x 32 tokens)"
$prompts = @("The capital of France is", "def fibonacci(n):", "Classify the sentiment: I love this product. Answer:", "Q: Is the sky blue? Reply yes or no.`nA:")
$idmap = @{ "The capital of France is"="504,3575,282,4649,314"; "def fibonacci(n):"="1604,3987,46477,24,94,727"; "Classify the sentiment: I love this product. Answer:"="8530,1282,260,19025,42,339,2606,451,1406,30,19842,42"; "Q: Is the sky blue? Reply yes or no.`nA:"="65,42,1431,260,6376,4461,47,2720,318,9805,355,787,30,198,49,42" }  # from llama-tokenize --ids
$plist = @(); $single = @()
foreach ($p in $prompts) {
  $pid_ = $idmap[$p]
  $plist += $pid_
  $o = (& .\out\smol_sm11.exe $M $pid_ 32 both 2>&1) -join "`n"; T "exit=$LASTEXITCODE len=$($o.Length) ids=$pid_"; T ($o -split "`n" | Select-String "abort|resident|tps|fail|err")
  $mp = [regex]::Match($o, 'match_prefix=([0-9/]+)').Groups[1].Value
  $single += [regex]::Match($o, 'gpu_ids=([0-9,]+)').Groups[1].Value
  T "verify [$($p.Replace("`n",' '))] GPU vs CPU-ref match_prefix=$mp"
}
P "MILESTONE: bench C - SPSC-ring decision server, 4 requests x 32 tok, inflight 1 vs 2 (double-buffered)"
$joined = ($plist -join ';')
foreach ($inf in 1, 2) {
  $o = (& .\out\smol_sm11.exe $M $joined 32 serve $inf 2>&1) -join "`n"; T ($o -split "`n" | Select-String 'serve|vram|resident|abort|req')
  $res["serve_inf$inf"] = [regex]::Match($o, '-> ([0-9.]+) tok/s').Groups[1].Value
  $ok = $true; for ($i = 0; $i -lt $plist.Count; $i++) { $g = [regex]::Match($o, "req${i}_ids=([0-9,]+)").Groups[1].Value; if (-not $g -or $g -ne $single[$i]) { $ok = $false } }
  $res["serve_inf${inf}_ids_equal_single"] = $ok; T "serve inflight=$inf outputs identical to single runs: $ok"
}
P "MILESTONE: bench D - concurrency: CPU coder (llama-bench, CPU0, 1 thread) + GPU decision (CPU1)"
$env:SMOL_CTX="64"
function CpuBench() { $o = (& E:\temp\llama-cpu\llama-bench.exe -m E:\temp\llama-cpu\stories15M-q4_0.gguf -t 1 -p 0 -n 128 -r 2 -o csv 2>$null) | Out-String; return [regex]::Match($o, '"tg128","[^"]*","([0-9.]+)"|,([0-9.]+),[0-9.]+\s*$').Value }
$cpuAlone = (Start-Job { Set-Location E:\temp\gpu-legacy; [Diagnostics.Process]::GetCurrentProcess().ProcessorAffinity = 1; & E:\temp\llama-cpu\llama-bench.exe -m E:\temp\llama-cpu\stories15M-q4_0.gguf -t 1 -p 0 -n 128 -r 2 2>$null | Out-String } | Wait-Job | Receive-Job)
T "CPU coder alone:"; T $cpuAlone
$gj = Start-Job -ArgumentList $M, $joined { param($M, $joined) Set-Location E:\temp\gpu-legacy; $env:SMOL_CTX="64"; [Diagnostics.Process]::GetCurrentProcess().ProcessorAffinity = 2; (& .\out\smol_sm11.exe $M ($joined + ';' + $joined) 32 serve 2 2>&1) | Out-String }
Start-Sleep 6
$cj = Start-Job { Set-Location E:\temp\gpu-legacy; [Diagnostics.Process]::GetCurrentProcess().ProcessorAffinity = 1; & E:\temp\llama-cpu\llama-bench.exe -m E:\temp\llama-cpu\stories15M-q4_0.gguf -t 1 -p 0 -n 128 -r 2 2>$null | Out-String }
$cpuCon = $cj | Wait-Job | Receive-Job; $gpuCon = $gj | Wait-Job | Receive-Job
T "CPU coder concurrent:"; T $cpuCon; T "GPU decision concurrent:"; T ($gpuCon -split "`n" | Select-String 'serve|vram|resident|abort')
$sj = Start-Job { Set-Location E:\temp\gpu-legacy; $env:SM11_FULL_FWD="1"; $env:OMP_NUM_THREADS="1"; [Diagnostics.Process]::GetCurrentProcess().ProcessorAffinity = 2; (& .\out\run_sm11.exe stories15M.bin -t 0 -n 256 -i "Once upon a time" 2>&1) | Out-String }
Start-Sleep 3
$cj2 = Start-Job { [Diagnostics.Process]::GetCurrentProcess().ProcessorAffinity = 1; & E:\temp\llama-cpu\llama-bench.exe -m E:\temp\llama-cpu\stories15M-q4_0.gguf -t 1 -p 0 -n 128 -r 2 2>$null | Out-String }
$cpuCon2 = $cj2 | Wait-Job | Receive-Job; $sOut = $sj | Wait-Job | Receive-Job
T "CPU coder concurrent with stories15M async:"; T $cpuCon2; T ("stories15M async concurrent: " + [regex]::Match($sOut, 'achieved tok/s: ([0-9.]+)').Value)
P "MILESTONE: summary"; T ($res | Out-String)
P "MILESTONE: bench_async.ps1 done"
