cd E:\temp\gpu-legacy; $env:PATH="E:\temp\tools\mingw64\bin;$env:PATH"; $L="E:\temp\gpu-legacy\progress.log"; $M="E:\temp\models\SmolLM2-135M-Instruct.Q4_0.gguf"
"$(Get-Date -f s) MILESTONE e2e cold-tuned" | Add-Content $L
$cfgs=[ordered]@{ "v4MR2 (default)"=@{SMOL_X="0"}; "X cold-tuned"=@{SMOL_X="1"}; "q4cls v4MR2"=@{SMOL_X="0";SMOL_CLS="q4"}; "q4cls X cold-tuned"=@{SMOL_X="1";SMOL_CLS="q4"} }
foreach($k in $cfgs.Keys){ Remove-Item Env:SMOL_X,Env:SMOL_CLS -ErrorAction SilentlyContinue; foreach($e in $cfgs[$k].GetEnumerator()){ Set-Item "Env:$($e.Key)" $e.Value }
  foreach($ids in "8530,128","65,42,14"){ $o=(& .\out\smol_sm11.exe $M $ids 32 both 2>&1) -join "`n"; $t=($o -split "`n" | Select-String "gpu_tps|match|tok_lat|cu err|resident" | % Line) -join " | "; "E2C [$k] prompt=$ids $t" | Add-Content $L } }
"$(Get-Date -f s) MILESTONE job8 done" | Add-Content $L
