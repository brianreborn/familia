cd E:\temp\gpu-legacy; $env:PATH="E:\temp\tools\mingw64\bin;$env:PATH"; $L="E:\temp\gpu-legacy\progress.log"; $M="E:\temp\models\SmolLM2-135M-Instruct.Q4_0.gguf"
"$(Get-Date -f s) MILESTONE e2e MR configs + q8 tex classifier" | Add-Content $L
$cfgs=[ordered]@{ "base v4MR2+oldq8"=@{SMOL_X="0";SMOL_Q8M="0"}; "v4MR2+q8tex4"=@{SMOL_X="0";SMOL_Q8M="4"}; "X mixed(4,3,5,4)+q8tex4"=@{SMOL_X="1";SMOL_Q8M="4"}; "X all MR4+q8tex4"=@{SMOL_X="1";SMOL_Q8M="4";SMOL_XS1="4,4,3,8";SMOL_XS2="4,8,2,16"}; "X all MR3+q8tex4"=@{SMOL_X="1";SMOL_Q8M="4";SMOL_XS0="3,4,2,16";SMOL_XS2="3,8,2,8";SMOL_XS3="3,4,2,16"} }
foreach($k in $cfgs.Keys){ foreach($v in "SMOL_X","SMOL_Q8M","SMOL_XS0","SMOL_XS1","SMOL_XS2","SMOL_XS3"){ Remove-Item "Env:$v" -ErrorAction SilentlyContinue }; foreach($e in $cfgs[$k].GetEnumerator()){ Set-Item "Env:$($e.Key)" $e.Value }
  foreach($ids in "8530,128","65,42,14"){ $o=(& .\out\smol_sm11.exe $M $ids 32 both 2>&1) -join "`n"; $t=($o -split "`n" | Select-String "gpu_tps|match|tok_lat|cu err" | % Line) -join " | "; "E2E [$k] prompt=$ids $t" | Add-Content $L } }
foreach($v in "SMOL_X","SMOL_Q8M","SMOL_XS0","SMOL_XS1","SMOL_XS2","SMOL_XS3"){ Remove-Item "Env:$v" -ErrorAction SilentlyContinue }
"$(Get-Date -f s) MILESTONE warm coder-alone baseline" | Add-Content $L
[Diagnostics.Process]::GetCurrentProcess().ProcessorAffinity=1
& E:\temp\llama-cpu\llama-bench.exe -m E:\temp\llama-cpu\stories15M-q4_0.gguf -t 1 -p 0 -n 32 -r 1 2>$null | Out-Null
foreach($r in 1,2){ $o=(& E:\temp\llama-cpu\llama-bench.exe -m E:\temp\llama-cpu\stories15M-q4_0.gguf -t 1 -p 0 -n 64 -r 2 2>$null | Out-String); "CODER warm alone rep=$r t/s=$(([regex]::Match($o,'tg64\s*\|\s*([0-9.]+)')).Groups[1].Value)" | Add-Content $L }
$p=Start-Process .\out\smol_sm11.exe -ArgumentList "$M 1,2,3 120 gpu" -PassThru -WindowStyle Hidden -RedirectStandardOutput "e2e_conc.txt"; Start-Sleep 1; try{$p.ProcessorAffinity=2}catch{}; Start-Sleep 5
$o=(& E:\temp\llama-cpu\llama-bench.exe -m E:\temp\llama-cpu\stories15M-q4_0.gguf -t 1 -p 0 -n 64 -r 2 2>$null | Out-String); $p.WaitForExit()
"CODER concurrent t/s=$(([regex]::Match($o,'tg64\s*\|\s*([0-9.]+)')).Groups[1].Value) | gpu $((Get-Content e2e_conc.txt | Select-String 'gpu_tps|wait mode' | % Line) -join ' | ')" | Add-Content $L
[Diagnostics.Process]::GetCurrentProcess().ProcessorAffinity=3
"$(Get-Date -f s) MILESTONE bench_async full" | Add-Content $L
& powershell -NoProfile -File E:\temp\gpu-legacy\bench_async.ps1 *>&1 | Out-Null
"$(Get-Date -f s) MILESTONE job6 done" | Add-Content $L
