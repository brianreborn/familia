cd E:\temp\gpu-legacy; $env:PATH="E:\temp\tools\mingw64\bin;$env:PATH"; $L="E:\temp\gpu-legacy\progress.log"; $M="E:\temp\models\SmolLM2-135M-Instruct.Q4_0.gguf"
gcc -O2 -march=native -o out\smol_sm11.exe smol_sm11.c -lm *>> $L; if($LASTEXITCODE){ "BUILD FAILED" | Add-Content $L; exit }
"$(Get-Date -f s) MILESTONE verify replay-tuned defaults" | Add-Content $L
foreach($c in "","q4"){ if($c){$env:SMOL_CLS=$c}else{Remove-Item Env:SMOL_CLS -ErrorAction SilentlyContinue}
 foreach($ids in "8530,128","65,42,14"){ $o=(& .\out\smol_sm11.exe $M $ids 32 both 2>&1) -join "`n"; $t=($o -split "`n" | Select-String "resident \d+ MiB \(|gpu_tps|match|tok_lat|cu err" | % { $_.Line -replace ', work chunks.*','' }) -join " | "; "DEF cls=$c prompt=$ids $t" | Add-Content $L } }
"$(Get-Date -f s) MILESTONE job12 done" | Add-Content $L
