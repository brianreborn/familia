cd E:\temp\gpu-legacy; $env:PATH="E:\temp\tools\mingw64\bin;$env:PATH"; $L="E:\temp\gpu-legacy\progress.log"; $M="E:\temp\models\SmolLM2-135M-Instruct.Q4_0.gguf"; $B="E:\temp\llama-cpu\llama-bench.exe"
"$(Get-Date -f s) MILESTONE job14 clean idle run" | Add-Content $L
$env:SMOL_KBENCH=1; $env:SMOL_KB_REPLAY=1; $r=& .\out\smol_sm11.exe $M "1,2,3" 2 gpu 2>&1 | Select-String "^REPLAY|cu err|vram free|resident \d+ MiB \(" | % Line; $r | % { "J14 $_" } | Add-Content $L
Remove-Item Env:SMOL_KBENCH,Env:SMOL_KB_REPLAY
$h=@{}; foreach($x in $r){ if($x -match 'pass 1 shape (\d) best MR=(\d+) RG=(\d+) BG=(\d+) G=(\d+)'){ $h["SMOL_XS$($matches[1])"]="$($matches[2]),$($matches[3]),$($matches[4]),$($matches[5])" }; if($x -match 'q8cls best MR=(\d+) RG=(\d+) BG=(\d+) G=(\d+)'){ $h["SMOL_Q8M"]=$matches[1]; $h["SMOL_M8CFG"]="$($matches[2]),$($matches[3]),$($matches[4])" } }
"J14CFG $(($h.GetEnumerator()|%{"$($_.Key)=$($_.Value)"}) -join ' ')" | Add-Content $L
foreach($rep in 1,2){ foreach($run in @(@("default",@{}),@("tuned",$h))){ Get-ChildItem Env: | ? Name -match '^SMOL_' | % { Remove-Item "Env:$($_.Name)" }; foreach($e in $run[1].GetEnumerator()){ Set-Item "Env:$($e.Key)" $e.Value }
  foreach($ids in "8530,128","65,42,14"){ $o=(& .\out\smol_sm11.exe $M $ids 32 both 2>&1) -join "`n"; $t=($o -split "`n" | Select-String "resident \d+ MiB \(|gpu_tps|match|tok_lat|cu err" | % { $_.Line -replace ', work chunks.*','' }) -join " | "; "J14E rep=$rep [$($run[0])] prompt=$ids $t" | Add-Content $L } } }
Get-ChildItem Env: | ? Name -match '^SMOL_' | % { Remove-Item "Env:$($_.Name)" }
"$(Get-Date -f s) MILESTONE job14 bench_async" | Add-Content $L
& powershell -NoProfile -File E:\temp\gpu-legacy\bench_async.ps1 *>&1 | Out-Null
"$(Get-Date -f s) MILESTONE job14 coder combo" | Add-Content $L
function CB($a){ $o=(& $B -m $M -p 64 -n 32 -r 2 $a.Split(' ') 2>$null | Out-String); $tg=([regex]::Match($o,'tg32\s*\|\s*([0-9.]+ \S+ [0-9.]+)')).Groups[1].Value; "tg32=$tg" }
& $B -m $M -p 0 -n 16 -r 1 -t 1 2>$null | Out-Null
foreach($c in "-t 1 -C 0x1 --cpu-strict 1","-t 2"){ "J14C alone [$c] $(CB $c)" | Add-Content $L }
Remove-Item gpu.stop,gpu_bg.log -ErrorAction SilentlyContinue
$g=Start-Process powershell -PassThru -WindowStyle Hidden -ArgumentList "-NoProfile -Command `"cd E:\temp\gpu-legacy; while(-not (Test-Path gpu.stop)){ `$p=Start-Process .\out\smol_sm11.exe -ArgumentList '$M 1,2,3;8530,128;65,42,14;1,2,3 32 serve 2' -PassThru -NoNewWindow -RedirectStandardOutput gpu_bg.txt; try{`$p.ProcessorAffinity=2}catch{}; `$p.WaitForExit(); (Get-Content gpu_bg.txt | Select-String '^serve').Line | Add-Content gpu_bg.log }`""
Start-Sleep 8; foreach($c in "-t 1 -C 0x1 --cpu-strict 1","-t 2"){ "J14C withGPU [$c] $(CB $c)" | Add-Content $L }
New-Item gpu.stop -Force | Out-Null; $g.WaitForExit(60000) | Out-Null
"J14C GPU during: " + ((Get-Content gpu_bg.log -ErrorAction SilentlyContinue | % { ([regex]::Match($_,'([0-9.]+) tok/s')).Groups[1].Value }) -join ',') | Add-Content $L
"$(Get-Date -f s) MILESTONE job14 done" | Add-Content $L
