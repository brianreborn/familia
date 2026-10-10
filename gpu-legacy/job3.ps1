cd E:\temp\gpu-legacy; $env:PATH="E:\temp\tools\mingw64\bin;$env:PATH"; $L="E:\temp\gpu-legacy\progress.log"; $M="E:\temp\models\SmolLM2-135M-Instruct.Q4_0.gguf"; $env:SMOL_V5=0
function Coder(){ $o=(& E:\temp\llama-cpu\llama-bench.exe -m E:\temp\llama-cpu\stories15M-q4_0.gguf -t 1 -p 0 -n 64 -r 2 2>$null | Out-String); ([regex]::Match($o,'tg64\s*\|\s*([0-9.]+ ± [0-9.]+)')).Groups[1].Value }
"$(Get-Date -f s) MILESTONE wait-mode A/B (0=spin64+block, 1=work+spin+block, 2=pure spin)" | Add-Content $L
[Diagnostics.Process]::GetCurrentProcess().ProcessorAffinity=1; "WM coder alone t/s=$(Coder)" | Add-Content $L
foreach($rep in 1,2){ foreach($wm in 0,1,2){ $env:SMOL_WAIT=$wm
  foreach($ids in "8530,128","65,42,14"){ $o=(& .\out\smol_sm11.exe $M $ids 32 both 2>&1) -join "`n"; $t=($o -split "`n" | Select-String "gpu_tps|match|wait mode|cu err" | % Line) -join " | "; "WM rep=$rep mode=$wm prompt=$ids $t" | Add-Content $L }
  $o=(& .\out\smol_sm11.exe $M "1,2,3;8530,128;65,42,14;1,2,3" 32 serve 2 2>&1 | Select-String "^serve" | % Line); "WM rep=$rep mode=$wm $o" | Add-Content $L
  $p=Start-Process .\out\smol_sm11.exe -ArgumentList "$M 1,2,3 120 gpu" -PassThru -WindowStyle Hidden -RedirectStandardOutput "wm_gpu_$wm.txt"; Start-Sleep 1; try{$p.ProcessorAffinity=2}catch{}
  Start-Sleep 6; $c=Coder; $p.WaitForExit(); $g=(Get-Content "wm_gpu_$wm.txt" | Select-String "gpu_tps|wait mode" | % Line) -join " | "; "WM rep=$rep mode=$wm concurrent coder t/s=$c | gpu $g" | Add-Content $L } }
"$(Get-Date -f s) MILESTONE job3 done" | Add-Content $L
